"""
task_executor.py — Single-Task LLM Execution Engine.

Extracted from LLMOrchestrator.execute_task() which previously embedded
197 lines of sandbox routing, tiered provider selection, prompt assembly,
and change-task LLM loop directly on the orchestrator instance.

Responsibilities:
  - Parse sandbox_mode and effort tier from memory.md
  - Route to heavy or fast provider based on effort
  - Assemble the per-task prompt payload with CodeGraph/checkpoint protocols
  - Dispatch via _run_with_tools and handle BudgetExhaustedException
  - Deterministic short-circuit for validation tasks (0 LLM tokens)
  - Post-execution garbage artifact sweep (non-blocking git subprocess)

Dependency injection:
  TaskExecutor(orchestrator) receives the live LLMOrchestrator instance.
  All state access (providers, budget_manager, plugin_root, etc.) is via
  the orchestrator reference — no state is copied or held locally.

Usage:
  WaveExecutor and test callers instantiate TaskExecutor(orchestrator)
  and call execute_task(...) directly.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import re
import subprocess
import sys
import uuid
from typing import TYPE_CHECKING

from yani_engine.core.config import config
from yani_engine.core.locks import _MEMORY_MUTEX, get_registry_lock
from yani_engine.core.state import (
    ASTMemoryMapper,
    append_session_log_row,
    flush_task_registry,
    update_task_registry_row,
)
from yani_engine.core.sandbox import execute_bash
from yani_engine.core.state import read_file

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator


class TaskExecutor:
    """Stateless single-task execution context.

    Instantiated once per task by WaveExecutor._worker(). Reads all
    required state from the injected orchestrator reference.
    """

    def __init__(self, orchestrator: "LLMOrchestrator") -> None:
        self._o = orchestrator

    async def execute_task(
        self, task_id: str, description: str = "", worker_id: str = None
    ) -> None:
        """Execute a single task end-to-end.

        Reads memory.md atomically, routes to the appropriate provider
        tier, assembles the prompt payload, and runs the LLM tool loop.

        Raises:
            BudgetExhaustedException: re-raised after marking task as
                interrupted, so WaveExecutor can propagate it upward.
        """
        from yani_engine.core.orchestrator import BudgetExhaustedException
        from yani_engine.core.sandbox import _ensure_warm_sandbox

        o = self._o  # shorthand reference

        # ------------------------------------------------------------------
        # 1. Read memory.md atomically
        # ------------------------------------------------------------------
        mem_content = ""
        try:
            async with _MEMORY_MUTEX:
                async with get_registry_lock():
                    if os.path.exists("memory.md"):
                        with open("memory.md", "r", encoding="utf-8") as f:
                            mem_content = f.read()
        except Exception:
            mem_content = ""

        # ------------------------------------------------------------------
        # 2. Resolve description from memory if omitted
        # ------------------------------------------------------------------
        if not description and mem_content:
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(mem_content, "###", task_id)
            if start_idx != -1:
                first_line = mem_content.splitlines()[start_idx].strip()
                description = (
                    first_line.replace(f"### {task_id}", "").lstrip(": ").strip()
                    or f"Task {task_id}"
                )
            else:
                description = f"Task {task_id}"
        elif not description:
            description = f"Task {task_id}"

        # ------------------------------------------------------------------
        # 3. Parse sandbox_mode from memory.md Config block
        # ------------------------------------------------------------------
        o.sandbox_mode = getattr(o, "sandbox_mode", "yani-base")
        if mem_content:
            config_start, config_end = ASTMemoryMapper.locate_heading_block(
                mem_content, "##", "Config"
            )
            if config_start != -1:
                for line in mem_content.splitlines()[config_start:config_end]:
                    if "- sandbox_mode:" in line:
                        o.sandbox_mode = line.split(":", 1)[1].strip()

        print(f"Initializing isolated sandbox ({o.sandbox_mode}) for task {task_id}...")

        if not o.sandbox_mode.startswith("compose:") and o.sandbox_mode != "native":
            await _ensure_warm_sandbox(worker_id or task_id, sandbox_mode=o.sandbox_mode)

        print(f"Executing task {task_id}: {description}")

        # ------------------------------------------------------------------
        # 4. Claim task with session ID
        # ------------------------------------------------------------------
        session_id = (
            f"S-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        )
        await update_task_registry_row(task_id, "in_progress", session_id)
        await append_session_log_row(session_id, task_id)

        # ------------------------------------------------------------------
        # 5. Parse effort tier and route to provider
        # ------------------------------------------------------------------
        effort = "small"
        if mem_content:
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(mem_content, "###", task_id)
            if start_idx != -1:
                task_block = "\n".join(mem_content.splitlines()[start_idx:end_idx])
                match = re.search(
                    r"- \*\*Estimated Effort\*\*: (small|medium|large)", task_block, re.IGNORECASE
                )
                if match:
                    effort = match.group(1).lower()

        active_provider = list(o.providers.values())[0]

        if effort in ["medium", "large"] or getattr(o, "model", config.model_fast) == config.model_heavy:
            target_model = config.model_heavy
            active_provider = o.providers.get("cloud", list(o.providers.values())[0])
            print(f"[Heavy Tier] Task {task_id} ({effort} effort) -> Routing to {target_model}")
        else:
            target_model = config.model_fast
            active_provider = o.providers.get(
                "local", o.providers.get("cloud", list(o.providers.values())[0])
            )
            print(f"[Fast Tier] Task {task_id} ({effort} effort) -> Routing to {target_model}")

        chat_session = await active_provider.create_chat_session(
            model_name=target_model,
            tools=o._get_tools_for_command("execute"),
        )
        system_instructions = await o.prompt_builder._get_system_instructions(command="execute", task_id=task_id)

        # ------------------------------------------------------------------
        # 6. Assemble prompt payload with CodeGraph/checkpoint protocols
        # ------------------------------------------------------------------
        cp_protocol = await read_file(os.path.join(o.plugin_root, "lib", "checkpoint-protocol.md"))

        if getattr(o, "is_codegraph_active", False):
            cg_protocol = await read_file(
                os.path.join(o.plugin_root, "lib", "codegraph-integration.md")
            )
            cg_injection = f"# CODEGRAPH INTEGRATION PROTOCOL\n{cg_protocol}"
        else:
            cg_injection = (
                "> **🚨 SYSTEM OVERRIDE: CODEGRAPH OFFLINE 🚨**\n"
                "> The structural analysis server is currently unreachable. You are explicitly "
                "authorized to BYPASS the 10-step data flow.\n"
                "> Rely exclusively on `read_file`, `read_code_block`, and `execute_bash` for "
                "codebase discovery."
            )

        is_cg_active = getattr(o, "is_codegraph_active", False)
        if is_cg_active:
            cg_rules = f"""1. You have already been provided the CodeGraph Integration and Checkpoint Protocols. Follow them strictly.
2. Follow the 10-step data flow for change tasks exactly.
3. Log your codegraph_impact result to memory.md task {task_id} CodeGraph Impact field."""
        else:
            cg_rules = """1. CODEGRAPH IS OFFLINE. Bypass the 10-step structural flow. Rely on bash and file reads.
2. Skip codegraph_impact logging.
3. Focus strictly on executing the code modification safely."""

        prompt_payload = f"""{system_instructions}

{cg_injection}

# CHECKPOINT PROTOCOL
{cp_protocol}

You are executing task {task_id}: {description}.

Mandatory rules:
{cg_rules}
4. The `write_file_with_review` tool AUTOMATICALLY handles the entire Checkpoint Protocol for you. Just pass the target file path and final content. Do not manually create rollbacks, tmp files, or checkpoints.
5. Do not modify any file listed in another in_progress task's Outputs.
6. Output compression: render your conversational replies at the appropriate caveman level.
7. Documentation lookup: check if this task involves external dependencies and consult context7 if needed.
8. **DO NOT USE BASH TO PARSE MEMORY.MD.** If you need to read `memory.md`, you MUST use the native `read_file` tool. If you need to update a task status, you MUST use the native `update_task_registry_row` tool. Do not write python scripts via bash to parse the ledger.
9. **STRICT DISCOVERY LIMITATIONS:** You are strictly forbidden from using `execute_bash` to run `find`, `ls`, or `which`. You MUST use `codegraph_search` for discovery.
10. **TOOL CONTEXT:** `run_rtk` is strictly for clearing token cache. NEVER pass python or bash scripts to `run_rtk`.
11. **TEST EXECUTION:** All testing MUST respect the project's native scheduling. Run tests via `uv run pytest` to ensure local `.venv` modules are loaded. A `ModuleNotFoundError` means you are using the wrong environment, not that the file is missing.
12. **NO DUMMY COMMANDS:** You are strictly forbidden from running empty test commands like `echo hello`, `whoami`, or `echo $PATH`. Every bash command must be a meaningful step toward completing the assigned task.
13. **CLEAN UP YOUR ARTIFACTS:** If you create any temporary bash scripts or python files (e.g., `run_test.sh`) to execute multi-line logic, you MUST delete them using `rm` via `execute_bash` immediately after they finish running. Do not leave garbage files in the workspace."""

        effort_to_iterations = {"small": 15, "medium": 25, "large": 40}
        max_iters = effort_to_iterations.get(effort, 25)

        # ------------------------------------------------------------------
        # 7. Execute
        # ------------------------------------------------------------------
        try:
            # Parse task type
            task_type = "change"
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(
                mem_content, "###", task_id
            )
            if start_idx != -1:
                t_block = "\n".join(mem_content.splitlines()[start_idx:end_idx])
                m_type = re.search(
                    r"- \*\*Type\*\*: (analysis|change|validation|report)", t_block, re.IGNORECASE
                )
                if m_type:
                    task_type = m_type.group(1).lower()

            if task_type == "validation":
                # TOKEN-FREE: deterministic test runner, no LLM loop
                test_cmd = "pytest tests/ -v"
                config_start, config_end = ASTMemoryMapper.locate_heading_block(
                    mem_content, "##", "Config"
                )
                if config_start != -1:
                    for line in mem_content.splitlines()[config_start:config_end]:
                        if "- test_command:" in line:
                            test_cmd = line.split(":", 1)[1].strip()

                print(
                    f"[Deterministic Validator] Task {task_id} is a validation task. "
                    "Running test suite natively (0 tokens)..."
                )
                print(f"Command: {test_cmd}")
                res = await execute_bash(test_cmd, sandbox_mode=o.sandbox_mode, task_id=task_id)
                print(res)

                if (
                    "No such file or directory" not in res
                    and "FAILED" not in res
                    and "error" not in res.lower()
                ):
                    await update_task_registry_row(task_id, "completed", session_id)
                    print(f"Task {task_id} validated successfully via sandbox run.")
                else:
                    raise RuntimeError(
                        "Sandbox validation failed. Test output indicated errors or missing files."
                    )
            else:
                # Snapshot untracked files before LLM loop (non-blocking)
                try:
                    pre_untracked = set(
                        (
                            await asyncio.to_thread(
                                subprocess.run,
                                ["git", "ls-files", "--others", "--exclude-standard"],
                                capture_output=True,
                                text=True,
                            )
                        ).stdout.splitlines()
                    )
                except Exception:
                    pre_untracked = set()

                # Standard LLM tool loop
                response = await o.agent_runner._run_with_tools(
                    chat_session,
                    prompt_payload,
                    active_provider,
                    task_id=task_id,
                    max_iterations=max_iters,
                    worker_id=worker_id,
                )
                o.budget_manager.check_and_harvest()

                # Sweep ephemeral artifacts leaked by the sandbox (non-blocking)
                try:
                    post_untracked = set(
                        (
                            await asyncio.to_thread(
                                subprocess.run,
                                ["git", "ls-files", "--others", "--exclude-standard"],
                                capture_output=True,
                                text=True,
                            )
                        ).stdout.splitlines()
                    )
                    cwd_real = os.path.realpath(os.getcwd())
                    for garbage_file in post_untracked - pre_untracked:
                        abs_path = os.path.realpath(garbage_file)
                        if (
                            abs_path.startswith(cwd_real)
                            and os.path.exists(abs_path)
                            and not garbage_file.startswith(".yani/")
                        ):
                            if garbage_file.endswith(".tmp") or garbage_file.endswith(".sh"):
                                print(f"🧹 Purging ephemeral artifact leaked by sandbox: {garbage_file}")
                                await asyncio.to_thread(os.remove, abs_path)
                except Exception:
                    pass

                print(f"Task {task_id} completed: {getattr(response, 'text', str(response))}")
                await update_task_registry_row(task_id, "awaiting-review")
                await flush_task_registry()

        except BudgetExhaustedException:
            print(
                f"Task {task_id} interrupted: Budget exhausted at "
                f"{o.budget_manager.estimated_tokens} tokens.",
                file=sys.stderr,
            )
            await update_task_registry_row(task_id, "interrupted")
            await flush_task_registry()
            if hasattr(o, "_graceful_shadow_shutdown"):
                await o._graceful_shadow_shutdown(task_id)
            else:
                await o._graceful_shutdown(task_id)
            raise
