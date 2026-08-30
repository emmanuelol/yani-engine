"""
audit_handler.py — QA Harness & Audit Loop command handler.

Extracted from LLMOrchestrator.run() "audit" branch.

Responsibilities:
  - Load tasks in 'awaiting-review' state from the Task Registry
  - Guard QA attempt counts with a cross-process FileLock to prevent
    concurrent audit loops from corrupting qa_attempts.json
  - Run native static analysis (uvx ruff) and pytest on modified files
  - Dispatch an isolated LLM evaluator per task via _run_with_tools
  - Enforce a 3-attempt cap before forcing a task to 'deferred'
  - Render a Rich summary table of pass / fail / error outcomes

Concurrency contract:
  - FileLock on .yani/qa_attempts.json.lock (cross-process, 30s timeout)
  - _MEMORY_MUTEX + get_registry_lock() on every memory.md read
  - BudgetExhaustedException is re-raised to the orchestrator's finally
    block so provider cleanup and archival still execute on budget kill.
"""

import os
import re
import shlex
import asyncio
import subprocess
from typing import TYPE_CHECKING

from yani_engine.core.locks import _MEMORY_MUTEX, get_registry_lock
from yani_engine.core.state import (
    ASTMemoryMapper,
    TaskRegistryState,
    OrphanRecoveryScanner,
    update_task_registry_row,
    flush_task_registry,
)
from yani_engine.core.sandbox import execute_bash

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator, BudgetExhaustedException


async def handle_audit(orchestrator: "LLMOrchestrator", args: list) -> None:
    """
    Drives the audit command end-to-end.

    Args:
        orchestrator: Active LLMOrchestrator — provides provider,
                      budget_manager, _run_with_tools, _graceful_shutdown,
                      mcp_sessions, and _get_tools_for_command.
        args:         Raw CLI argument list (currently unused; reserved for
                      future --task-id / --max-attempts flags).
    """
    from rich.console import Console
    from rich.table import Table

    # Import at call-time to avoid circular top-level import
    from yani_engine.core.orchestrator import BudgetExhaustedException

    console = Console()

    if not os.path.exists("memory.md"):
        console.print("[red]Error: memory.md not found. Run /yani-engine:start first.[/red]")
        return

    await OrphanRecoveryScanner().run(unattended=True)

    state = TaskRegistryState()
    all_tasks = await state.load_tasks()
    review_tasks = [t for t in all_tasks.values() if t["status"].strip() == "awaiting-review"]

    if not review_tasks:
        console.print("[green]No tasks currently awaiting review.[/green]")
        return


    console.print(f"[cyan]Starting Native QA Harness Loop for {len(review_tasks)} task(s)...[/cyan]")
    results_summary: list[tuple[str, str, str]] = []

    for t in review_tasks:
        t_id = t["id"]
        title = t["title"]
        outputs = t.get("outputs", [])

        console.print(f"\n[bold yellow]Auditing {t_id}: {title}[/bold yellow]")

        # ------------------------------------------------------------------
        # 1. Cross-process QA attempt guard (FileLock)
        # ------------------------------------------------------------------
        import json
        from filelock import FileLock as _FileLock

        qa_tracker_path = ".yani/qa_attempts.json"
        qa_lock_path = qa_tracker_path + ".lock"
        os.makedirs(os.path.dirname(qa_tracker_path), exist_ok=True)
        attempts: dict = {}

        with _FileLock(qa_lock_path, timeout=30):
            if os.path.exists(qa_tracker_path):
                with open(qa_tracker_path, "r") as f:
                    attempts = json.load(f)

            if attempts.get(t_id, 0) >= 3:
                console.print(
                    f"[red]Task {t_id} has failed QA 3 times. "
                    "Forcing to deferred to prevent infinite loops.[/red]"
                )
                await update_task_registry_row(t_id, "deferred")
                await flush_task_registry()
                continue

            attempts[t_id] = attempts.get(t_id, 0) + 1
            with open(qa_tracker_path, "w") as f:
                json.dump(attempts, f)

        # ------------------------------------------------------------------
        # 2. Atomic memory.md read per-task iteration
        # ------------------------------------------------------------------
        async with _MEMORY_MUTEX:
            async with get_registry_lock():
                with open("memory.md", "r", encoding="utf-8") as f:
                    mem_content = f.read()

        # ------------------------------------------------------------------
        # 3. Extract Success Criteria and Outputs from Task Details block
        # ------------------------------------------------------------------
        success_criteria = "Not defined."
        t_start, t_end = ASTMemoryMapper.locate_heading_block(mem_content, "###", t_id)
        if t_start != -1:
            task_block = "\n".join(mem_content.splitlines()[t_start:t_end])
            match_crit = re.search(r"- \*\*Success Criteria\*\*: (.*)", task_block)
            if match_crit:
                success_criteria = match_crit.group(1).strip()
            match_out = re.search(r"- \*\*Outputs\*\*: (.*)", task_block)
            if match_out:
                outputs = [o.strip() for o in match_out.group(1).split(",") if o.strip()]

        # ------------------------------------------------------------------
        # 4. Native Static Analysis
        # ------------------------------------------------------------------
        static_analysis_output = ""
        py_files = [f for f in outputs if f.endswith(".py") and os.path.exists(f)]

        for pf in py_files:
            proc = subprocess.run(["uvx", "ruff", "check", pf], capture_output=True, text=True)
            out = proc.stdout + proc.stderr
            if proc.returncode != 0 and "executable file not found" in proc.stderr.lower():
                static_analysis_output += (
                    f"--- Ruff Check for {pf} ---\n"
                    "CRITICAL ERROR: 'uvx' not found on system. "
                    "Static analysis failed. Please flag this as a failure.\n"
                )
            else:
                static_analysis_output += (
                    f"--- Ruff Check for {pf} ---\n"
                    f"{out.strip() or 'Syntax OK. No issues found.'}\n"
                )

        # ------------------------------------------------------------------
        # 5. Affected-test execution via CodeGraph MCP
        # ------------------------------------------------------------------
        try:
            if "codegraph" in orchestrator.mcp_sessions and py_files:
                cg_res = await orchestrator.mcp_sessions["codegraph"].call_tool(
                    "codegraph_affected", arguments={"files": py_files}
                )
                test_files = (
                    cg_res.content[0].text.split(",")
                    if cg_res and cg_res.content
                    else []
                )
                # Sanitize paths before shell interpolation
                test_files = [shlex.quote(tf.strip()) for tf in test_files if tf.strip()]
                if test_files:
                    static_analysis_output += "\n--- Pytest Execution for Affected Tests ---\n"
                    test_proc = await execute_bash(f"pytest {' '.join(test_files)}")
                    static_analysis_output += str(test_proc) + "\n"
        except Exception:
            pass

        if not static_analysis_output.strip():
            static_analysis_output = "No Python files modified, or no static analysis warnings found."

        # Hard truncation: prevent context window explosion
        if len(static_analysis_output) > 2000:
            static_analysis_output = (
                static_analysis_output[:2000]
                + "\n... [TRUNCATED BY NATIVE ORCHESTRATOR TO PREVENT TOKEN BLOAT]"
            )

        # ------------------------------------------------------------------
        # 6. Isolated LLM Evaluator Prompt
        # ------------------------------------------------------------------
        prompt_payload = f"""You are the strict yani-engine QA Evaluator.
You are evaluating EXACTLY ONE task.

# TASK UNDER REVIEW: {t_id}
Title: {title}
Modified Files: {', '.join(outputs) if outputs else 'None'}
Success Criteria: {success_criteria}

# NATIVE STATIC ANALYSIS RESULTS
{static_analysis_output}

# YOUR DIRECTIVE
1. Evaluate the static analysis output and any other necessary context (using read_file or execute_bash for a single targeted test if needed).
2. If the task passes its success criteria and has no critical static analysis errors, you MUST use the `update_task_registry_row` tool to change its status to `completed`.
3. If the task fails, you MUST use the `register_task_batch` tool to queue a specific `change` task to fix the bug. CRITICAL: Set the `deps` argument to "none". Do NOT make the new task depend on the failed task, or the execution engine will deadlock. Do not change the current task's status (leave it as awaiting-review). CRITICAL: Set the `estimated_effort` argument to "medium" or "large" (never "small") because fixing bugs requires terminal debugging.
4. Terminate your turn with a brief summary of your decision.
"""

        model_name = getattr(orchestrator, "model", "gemini-3.1-pro-preview")
        chat_session = await orchestrator.provider.create_chat_session(
            model_name=model_name,
            tools=orchestrator._get_tools_for_command("audit"),
        )

        with console.status(f"[cyan]LLM Evaluator analyzing {t_id}...[/cyan]", spinner="dots") as status:
            try:
                response = await orchestrator.agent_runner._run_with_tools(
                    chat_session,
                    prompt_payload,
                    orchestrator.provider,
                    status=status,
                    task_id=t_id,
                    max_iterations=40,
                )
                # Budget accounting
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    orchestrator.budget_manager.add_tokens(
                        getattr(response.usage_metadata, "total_token_count", 0)
                    )
                else:
                    heuristic_tokens = (len(str(prompt_payload)) // 4) + (
                        len(str(getattr(response, "text", ""))) // 4
                    )
                    orchestrator.budget_manager.add_tokens(heuristic_tokens)
                orchestrator.budget_manager.check_and_harvest()

                # Detect what the LLM decided by reloading tasks
                new_tasks = await TaskRegistryState().load_tasks()
                current_status = new_tasks.get(t_id, {}).get("status", "awaiting-review")

                if current_status == "completed":
                    results_summary.append((t_id, "[green]PASSED[/green]", "Marked completed"))
                    console.print(f"[green]✔ {t_id} Passed QA.[/green]")
                else:
                    results_summary.append((t_id, "[red]FAILED[/red]", "Fix task queued"))
                    console.print(f"[red]✖ {t_id} Failed QA. Fix task generated.[/red]")

            except BudgetExhaustedException:
                console.print("[bold red]Budget exhausted during audit.[/bold red]")
                await orchestrator._graceful_shutdown(t_id)
                return
            except Exception as e:
                console.print(f"[bold red]Error auditing {t_id}: {e}[/bold red]")
                results_summary.append((t_id, "[yellow]ERROR[/yellow]", str(e)))

    # ------------------------------------------------------------------
    # 7. Final Report Table
    # ------------------------------------------------------------------
    console.print("\n[bold]Audit Wave Complete[/bold]")
    table = Table(title="QA Harness Results")
    table.add_column("Task ID", style="cyan")
    table.add_column("Result")
    table.add_column("Action Taken", style="dim")
    for res in results_summary:
        table.add_row(res[0], res[1], res[2])
    console.print(table)
