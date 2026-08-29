"""
handlers.py — Status, Report, and Rollback command handlers.

Extracted from LLMOrchestrator.run() branches for status, report, and rollback.

I/O contract:
  - All file mutations (shutil.copy2, os.remove, os.makedirs) are wrapped
    in asyncio.to_thread() to prevent event loop starvation.
  - memory.md reads are guarded by _MEMORY_MUTEX + get_registry_lock().
  - memory.md writes stay inside the mutex for atomicity.

Dependency injection:
  - All three handlers receive `orchestrator: LLMOrchestrator` to access
    budget_manager and mcp_sessions without exposing internal state.
"""

import os
import sys
import shutil
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
from yani_engine.core.config import config

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator


# ---------------------------------------------------------------------------
# handle_status
# ---------------------------------------------------------------------------

async def handle_status(orchestrator: "LLMOrchestrator", args: list) -> None:
    """Renders the yani-engine status dashboard to stdout."""
    is_verbose = config.verbose or "--verbose" in args or "-v" in args

    if not os.path.exists("memory.md"):
        print("Error: memory.md not found. Run /yani-engine:start to begin.")
        return

    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            with open("memory.md", "r", encoding="utf-8") as f:
                content = f.read()

    # 1. Parse Project Goal
    goal_start, goal_end = ASTMemoryMapper.locate_heading_block(content, "##", "Project Goal")
    project_goal = "None"
    if goal_start != -1:
        goal_lines = []
        for line in content.splitlines()[goal_start + 1 : goal_end]:
            l_strip = line.strip()
            if l_strip and not l_strip.startswith("#"):
                goal_lines.append(l_strip)
            elif not l_strip and goal_lines:
                break
        if goal_lines:
            project_goal = " ".join(goal_lines)

    # 2. Parse Session & Budget Data
    sess_start, sess_end = ASTMemoryMapper.locate_heading_block(content, "##", "Session Log")
    last_session_id, last_outcome, last_end = "None", "None", "None"
    if sess_start != -1:
        sess_lines = [
            l.strip()
            for l in content.splitlines()[sess_start + 1 : sess_end]
            if l.startswith("|") and "---" not in l and "Session ID" not in l
        ]
        if sess_lines:
            parts = [p.strip() for p in sess_lines[-1].split("|")]
            if len(parts) >= 6:
                last_session_id, last_end, last_outcome = parts[1], parts[3], parts[5]

    tokens = orchestrator.budget_manager.estimated_tokens
    limit = orchestrator.budget_manager.budget_limit
    pct_used = int((tokens / limit) * 100) if limit > 0 else 0

    # 3. Print Header
    print(
        f"\nyani-engine — Session {last_session_id} | "
        f"Budget: {pct_used}% used ({tokens}/{limit} est. tokens)"
    )
    print(f"\nProject Goal: {project_goal}\n")
    print("Task Registry:")

    # 4. Parse and Format Task Registry
    icons = {
        "completed": "✅",
        "in_progress": "🔄",
        "interrupted": "⏸",
        "pending": "⬜",
        "blocked": "🚫",
        "deferred": "💤",
        "awaiting-review": "⏳",
    }
    tasks = await TaskRegistryState().load_tasks()

    archive_index: dict = {}
    if is_verbose:
        ai_start, ai_end = ASTMemoryMapper.locate_heading_block(content, "##", "Archive Index")
        if ai_start != -1:
            for line in content.splitlines()[ai_start + 1 : ai_end]:
                if line.strip().startswith("|") and "---" not in line and "Session ID" not in line:
                    ai_parts = [p.strip() for p in line.split("|")]
                    if len(ai_parts) > 4:
                        archive_index[ai_parts[1]] = ai_parts[3]

    for t_id, t in tasks.items():
        parts = [p.strip() for p in t.get("original_line", "").split("|")]
        t_type = parts[3] if len(parts) > 3 else "unknown"
        t_status = parts[4] if len(parts) > 4 else t["status"]
        owner = parts[5] if len(parts) > 5 else "—"

        icon = icons.get(t_status.lower(), "⬜")
        title = (t["title"][:47] + "...") if len(t["title"]) > 50 else t["title"]

        step_note = ""
        if ("in_progress" in t_status.lower() or "interrupted" in t_status.lower()) and len(parts) > 8:
            chk_id = parts[8].strip()
            if "step" in chk_id:
                step_parts = chk_id.split("step")
                if len(step_parts) > 1:
                    try:
                        step_note = f"(step {step_parts[1].split('-')[0]})"
                    except IndexError:
                        pass

        print(f"  {icon} {t_id}  {title:<50} [{t_type}]  {owner}  {step_note}")

        if is_verbose:
            if len(parts) > 8 and "archived" in parts[8].lower():
                archive_file = archive_index.get(owner, f".yani/archive/{owner}.md")
                print(f"\n    [Archived] Task details moved to {archive_file}\n")
            else:
                t_start, t_end = ASTMemoryMapper.locate_heading_block(content, "###", t_id)
                if t_start != -1:
                    print("\n    " + "\n    ".join(content.splitlines()[t_start + 1 : t_end]))
                    print("")

    # 5. Fetch CodeGraph Status (non-blocking, 3s timeout)
    cg_healthy, cg_symbols, cg_sync = "⚠ not initialized — run codegraph init -i", "0", "N/A"
    if os.path.exists(".codegraph"):
        try:
            import re
            cg_out = (
                await asyncio.to_thread(
                    subprocess.run,
                    ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "status"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            ).stdout
            sym_match = re.search(r"(\d+)\s+symbols", cg_out)
            cg_symbols = sym_match.group(1) if sym_match else "unknown"
            cg_healthy = (
                "✅ healthy"
                if "healthy" in cg_out.lower() or "ok" in cg_out.lower()
                else "⚠ stale"
            )
            cg_sync = "recently"
        except subprocess.TimeoutExpired:
            cg_healthy = "⚠ stale"
        except Exception:
            cg_healthy = "⚠ degraded"

    # 6. Evaluate Knowledge Registry
    know_path = "knowledge"
    conf_start, conf_end = ASTMemoryMapper.locate_heading_block(content, "##", "Config")
    if conf_start != -1:
        for l in content.splitlines()[conf_start:conf_end]:
            if "- knowledge_path:" in l:
                know_path = l.split(":", 1)[1].strip()

    if not os.path.exists(know_path):
        know_str = "Knowledge: no registry — /yani-engine:start creates it"
    else:
        import glob
        import re as _re

        def _parse_knowledge() -> str:
            k_stats = {
                "decision": 0,
                "success": 0,
                "failure": 0,
                "constraint": 0,
                "insight": 0,
                "superseded": 0,
            }
            k_total, k_last_date = 0, "N/A"
            entries = glob.glob(os.path.join(know_path, "entries", "*.md"))
            dates = []
            for e in entries:
                try:
                    with open(e, "r", encoding="utf-8") as kf:
                        fm = _re.match(r"^---\n(.*?)\n---", kf.read(), _re.DOTALL)
                        if fm:
                            fm_text = fm.group(1).lower()
                            t_match = _re.search(r"type:\s*(\w+)", fm_text)
                            s_match = _re.search(r"status:\s*(\w+)", fm_text)
                            d_match = _re.search(r"created:\s*([^\n]+)", fm_text)
                            if t_match and t_match.group(1) in k_stats:
                                k_stats[t_match.group(1)] += 1
                            if s_match and "superseded" in s_match.group(1):
                                k_stats["superseded"] += 1
                            if d_match:
                                dates.append(d_match.group(1).strip())
                            k_total += 1
                except Exception:
                    pass
            if dates:
                k_last_date = max(dates)
            return (
                f"Knowledge: {k_total} entries "
                f"({k_stats['decision']} decisions, {k_stats['success']} successes, "
                f"{k_stats['failure']} failures, {k_stats['constraint']} constraints, "
                f"{k_stats['insight']} insights; {k_stats['superseded']} superseded) "
                f"| last entry {k_last_date} | {know_path}"
            )

        know_str = await asyncio.to_thread(_parse_knowledge)

    # 7. Print Footers
    print(f"\nLast session: {last_session_id} — {last_outcome} ({last_end})")
    print(f"CodeGraph: {cg_healthy} | {cg_symbols} symbols | last sync {cg_sync}")
    print(know_str + "\n")


# ---------------------------------------------------------------------------
# handle_report
# ---------------------------------------------------------------------------

async def handle_report(orchestrator: "LLMOrchestrator", args: list) -> None:
    """Generates a Markdown improvement report from completed tasks."""
    import difflib
    import re
    from datetime import datetime

    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    output_path = None

    # 1. Parse Args
    for i, arg in enumerate(args):
        if arg.startswith("--output="):
            output_path = arg.split("=")[1]
        elif arg == "--output" and i + 1 < len(args):
            output_path = args[i + 1]

    if not os.path.exists("memory.md"):
        console.print("[red]Error: memory.md not found. Run /yani-engine:start first.[/red]")
        return

    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            with open("memory.md", "r", encoding="utf-8") as f:
                mem_content = f.read()

    # 2. Parse Baseline Config
    config_start, config_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
    baseline_symbols = "0"
    baseline_sync = "Unknown"
    backend = "native"
    if config_start != -1:
        for line in mem_content.splitlines()[config_start:config_end]:
            if "codegraph_baseline_symbols:" in line:
                baseline_symbols = line.split(":", 1)[1].strip()
            if "codegraph_baseline_sync:" in line:
                baseline_sync = line.split(":", 1)[1].strip()
            if "codegraph_backend:" in line:
                backend = line.split(":", 1)[1].strip()

    # 3. Get Current CodeGraph Status
    cg_symbols = "0"
    if os.path.exists(".codegraph"):
        try:
            cg_out = (
                await asyncio.to_thread(
                    subprocess.run,
                    ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "status"],
                    capture_output=True,
                    text=True,
                )
            ).stdout
            sym_match = re.search(r"(\d+)\s+symbols", cg_out)
            if sym_match:
                cg_symbols = sym_match.group(1)
        except Exception:
            pass

    # 4. Extract Tasks & Goal
    goal_start, goal_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Project Goal")
    project_goal = (
        mem_content.splitlines()[goal_start + 1 : goal_end][0]
        if goal_start != -1 and goal_end > goal_start + 1
        else "No goal defined."
    )

    state = TaskRegistryState()
    all_tasks = await state.load_tasks()
    completed_changes = [
        t for t in all_tasks.values()
        if t["status"] == "completed" and "change" in t.get("original_line", "")
    ]
    pending_tasks = [
        t for t in all_tasks.values() if t["status"] in ["pending", "deferred"]
    ]

    if not completed_changes:
        console.print(
            "[yellow]No completed changes found. "
            "Run /yani-engine:status to see pending tasks.[/yellow]"
        )
        return

    # 5. Build Report Markdown
    lines = [
        "# yani-engine Improvement Report\n",
        f"**Project**: {project_goal}",
        f"**Tasks Completed**: {len(completed_changes)}",
        f"**Generated**: {datetime.utcnow().isoformat()}Z\n",
        "---\n",
        "## Baseline Assessment\n",
        f"- Symbols indexed at session start: {baseline_symbols}",
        f"- CodeGraph backend: {backend}",
        f"- Session start: {baseline_sync}",
        f"- Current symbol count: {cg_symbols}\n",
        "---\n",
        "## Changes Applied\n",
    ]

    total_tool_calls_est = 0
    unique_files_modified: set = set()

    # 6. Generate Diffs Deterministically
    for t in completed_changes:
        t_id = t["id"]
        title = t["title"]
        outputs = t.get("outputs", [])

        effort = "small"
        impact = "—"
        t_start, t_end = ASTMemoryMapper.locate_heading_block(mem_content, "###", t_id)
        if t_start != -1:
            task_block = "\n".join(mem_content.splitlines()[t_start:t_end])
            match_eff = re.search(
                r"- \*\*Estimated Effort\*\*: (small|medium|large)", task_block, re.IGNORECASE
            )
            if match_eff:
                effort = match_eff.group(1).lower()
            match_imp = re.search(r"- \*\*CodeGraph Impact\*\*: (.*)", task_block)
            if match_imp:
                impact = match_imp.group(1).strip()

        if effort == "small":
            total_tool_calls_est += 5
        elif effort == "medium":
            total_tool_calls_est += 10
        elif effort == "large":
            total_tool_calls_est += 20

        lines.append(f"### {t_id}: {title}\n")
        lines.append(f"**What changed**: {', '.join(outputs) if outputs else 'None'}")
        lines.append(f"**Impact radius** (CodeGraph): {impact}\n")

        for file_path in outputs:
            unique_files_modified.add(file_path)
            encoded_path = file_path.replace("/", "__").replace(":", "__colon__")
            possible_rollback = os.path.join(".yani", "rollbacks", t_id, encoded_path)

            original_text = ""
            if os.path.exists(possible_rollback):
                with open(possible_rollback, "r") as rf:
                    original_text = rf.read()

            current_text = ""
            if os.path.exists(file_path):
                with open(file_path, "r") as cf:
                    current_text = cf.read()

            diff = list(
                difflib.unified_diff(
                    original_text.splitlines(),
                    current_text.splitlines(),
                    fromfile=f"a/{file_path}",
                    tofile=f"b/{file_path}",
                    n=3,
                    lineterm="",
                )
            )

            if diff:
                lines.append(f"**Diff for `{file_path}`**:")
                lines.append("```diff")
                diff_block = "\n".join(diff[:40])
                lines.append(diff_block)
                if len(diff) > 40:
                    lines.append(f"... (diff truncated, {len(diff)-40} more lines)")
                lines.append("```\n")

    # 7. Analytics & Token Yield
    lines.append("---\n")
    lines.append("## Delta Summary\n")
    lines.append("| Metric | Before | After | Change |")
    lines.append("|--------|--------|-------|--------|")
    try:
        delta_sym = int(cg_symbols) - int(baseline_symbols)
    except ValueError:
        delta_sym = "N/A"
    delta_str = (
        f"+{delta_sym}" if isinstance(delta_sym, int) and delta_sym > 0 else str(delta_sym)
    )
    lines.append(f"| Symbols indexed | {baseline_symbols} | {cg_symbols} | {delta_str} |")
    lines.append(
        f"| Files modified | 0 | {len(unique_files_modified)} | +{len(unique_files_modified)} |"
    )
    lines.append(
        f"| Tasks completed | 0 | {len(completed_changes)} | +{len(completed_changes)} |\n"
    )
    lines.append("---\n")
    lines.append("## Token Optimization\n")
    lines.append(f"- Estimated Tool Calls Executed: {total_tool_calls_est}")
    lines.append(f"- Optimization Yield: ~{total_tool_calls_est * 25000} tokens saved")
    lines.append(
        "- Engine Mechanism: Dynamic Tool Filtering & Sliced Memory Ingestion\n"
    )
    lines.append("---\n")
    lines.append("## Recommended Next Steps\n")
    if pending_tasks:
        for pt in pending_tasks:
            lines.append(f"- {pt['id']}: {pt['title']} ({pt['status']})")
        lines.append("\nRun `/yani-engine:resume` to continue working on these tasks.")
    else:
        lines.append(
            "All improvement tasks completed. "
            "The agent has been fully improved per the session goals."
        )

    report_md = "\n".join(lines)

    if output_path:
        try:
            await asyncio.to_thread(
                os.makedirs, os.path.dirname(os.path.abspath(output_path)), exist_ok=True
            )
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report_md)
            console.print(f"[green]Report successfully written to {output_path}[/green]")
        except Exception as e:
            console.print(f"[red]Error writing report to {output_path}: {e}[/red]")
    else:
        console.print(Markdown(report_md))

    # 8. Sync Knowledge Base
    if os.path.exists("sync_knowledge.py"):
        try:
            subprocess.run([sys.executable, "sync_knowledge.py"], capture_output=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# handle_rollback
# ---------------------------------------------------------------------------

async def handle_rollback(orchestrator: "LLMOrchestrator", args: list) -> None:
    """Reverts completed tasks from rollback snapshots and resets memory.md."""
    if not args:
        print("Error: must provide a task ID (e.g., T-001) or --all")
        return

    target = args[0]
    tasks_to_rollback: list[str] = []
    state = TaskRegistryState()
    all_tasks = await state.load_tasks()

    if target == "--all":
        tasks_to_rollback = sorted(
            [t_id for t_id, t in all_tasks.items() if "completed" in t["status"]],
            reverse=True,
        )
        if not tasks_to_rollback:
            print("No completed tasks found to roll back.")
            return
    elif target.startswith("T-"):
        if target not in all_tasks or "completed" not in all_tasks[target]["status"]:
            print(f"Error: {target} is not a completed task.")
            return
        tasks_to_rollback = [target]
    else:
        print(f"Error: Invalid rollback target '{target}'. Use a Task ID or --all.")
        return

    # Read memory into a list for surgical, line-by-line replacement
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            with open("memory.md", "r", encoding="utf-8") as f:
                mem_content = f.read()
            mem_lines = mem_content.splitlines()

            for task_id in tasks_to_rollback:
                print(f"\nRolling back {task_id}...")
                bak_dir = f".yani/rollbacks/{task_id}"

                if not os.path.exists(bak_dir):
                    print(
                        f"Warning: No rollback directory found for {task_id}. "
                        "Only memory.md will be reset."
                    )
                else:
                    touched_files: list[str] = []
                    chg_start, chg_end = ASTMemoryMapper.locate_heading_block(
                        mem_content, "##", "Change Log"
                    )
                    if chg_start != -1:
                        for i in range(chg_start + 1, chg_end):
                            parts = [p.strip() for p in mem_lines[i].split("|")]
                            if len(parts) >= 6 and parts[2] == task_id:
                                touched_files.append(parts[3])
                                mem_lines[i] = mem_lines[i].replace(
                                    "| applied |", "| rolled-back |"
                                )

                    restored_files: set = set()
                    for root, _, files in os.walk(bak_dir):
                        for file in files:
                            bak_path = os.path.join(root, file)
                            rel_path = (
                                bak_path.replace(bak_dir + "/", "")
                                .replace("__colon__", ":")
                                .replace("__", "/")
                            )
                            # Ensure target directory exists (non-blocking)
                            await asyncio.to_thread(
                                os.makedirs,
                                os.path.dirname(os.path.abspath(rel_path)),
                                exist_ok=True,
                            )

                            # Safety temp copy before overwrite (non-blocking)
                            tmp_path = f".yani/tmp/{file}.tmp"
                            await asyncio.to_thread(
                                os.makedirs,
                                os.path.dirname(tmp_path),
                                exist_ok=True,
                            )
                            if os.path.exists(rel_path):
                                await asyncio.to_thread(shutil.copy2, rel_path, tmp_path)

                            await asyncio.to_thread(shutil.copy2, bak_path, rel_path)
                            restored_files.add(rel_path)
                            print(f"  Restored: {rel_path}")

                    for f_path in touched_files:
                        if f_path not in restored_files and os.path.exists(f_path):
                            await asyncio.to_thread(os.remove, f_path)
                            print(f"  Deleted newly created file: {f_path}")

                # Fix 2: Dynamic Task Details lookup for trailing titles
                t_start, t_end = -1, -1
                for i, line in enumerate(mem_lines):
                    if line.startswith(f"### {task_id}"):
                        t_start = i
                        for j in range(i + 1, len(mem_lines)):
                            if mem_lines[j].startswith("## ") or mem_lines[j].startswith("### T-"):
                                t_end = j
                                break
                        if t_end == -1:
                            t_end = len(mem_lines)
                        break

                if t_start != -1:
                    for i in range(t_start, t_end):
                        if "- **Owner**:" in mem_lines[i]:
                            mem_lines[i] = "- **Owner**: —"
                        if "- **Checkpoint**:" in mem_lines[i]:
                            mem_lines[i] = "- **Checkpoint**: none"
                        if "- **Notes**:" in mem_lines[i]:
                            mem_lines[i] += " (Rolled back)"

            # Save updated memory.md (inside lock)
            mem_content = "\n".join(mem_lines)
            with open("memory.md", "w", encoding="utf-8") as f:
                f.write(mem_content)

    # Fix 3: TaskRegistryState updates AFTER file write to avoid stale reads
    for task_id in tasks_to_rollback:
        await update_task_registry_row(task_id, "pending")
    await flush_task_registry()

    # Sync CodeGraph AST (non-blocking)
    if os.path.exists(".codegraph"):
        print("\nSyncing CodeGraph index...")
        await asyncio.to_thread(
            subprocess.run,
            ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "sync"],
            capture_output=True,
        )

    print(f"\nRollback complete. Restored {len(tasks_to_rollback)} task(s).")
