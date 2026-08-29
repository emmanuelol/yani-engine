"""
executor.py — Wave Execution Engine.

Extracted from LLMOrchestrator.run() "execute" branch.

Responsibilities:
  - Drive the outer while-True wave loop via WavePlanner
  - Manage an asyncio.Queue of tasks per wave
  - Spawn and supervise worker coroutines (capped at safe_parallel)
  - Render Rich progress bar per wave
  - Propagate BudgetExhaustedException to caller for graceful shutdown
  - Trigger batch_diff_review after each wave completes

Design decision:
  The worker() inner function has been promoted to a method on
  WaveExecutor to eliminate the closure-scope lifetime issue: the
  original inner function held references to progress, queue,
  orchestrator, and budget_manager until the entire wave completed,
  preventing GC of those objects. As a method, lifetimes are explicit.

Concurrency contract:
  - max_parallel is read from memory.md Config once before the wave loop.
  - Worker count is hard-capped at min(3, max_parallel, len(wave)).
  - BudgetExhaustedException drains the queue before propagating.
  - asyncio.wait with FIRST_EXCEPTION cancels all remaining workers
    immediately on the first unhandled exception.
"""

import asyncio
import glob
import os
from typing import TYPE_CHECKING

from yani_engine.core.locks import _MEMORY_MUTEX, get_registry_lock
from yani_engine.core.state import (
    ASTMemoryMapper,
    TaskRegistryState,
    OrphanRecoveryScanner,
    update_task_registry_row,
    flush_task_registry,
)
from yani_engine.core.review_ui import batch_diff_review
from yani_engine.core.config import config

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator, BudgetExhaustedException


class WaveExecutor:
    """
    Drives the pending-task wave execution loop.

    Instantiate once per `execute` command invocation; call
    execute_pending_waves() to run all waves to completion.
    """

    def __init__(self, orchestrator: "LLMOrchestrator") -> None:
        self._orch = orchestrator

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def execute_pending_waves(self, args: list) -> None:
        """
        Full wave-loop entry point called from LLMOrchestrator.run().

        Args:
            args: Raw CLI argument list (forwarded for future flag support).
        """
        from yani_engine.core.orchestrator import BudgetExhaustedException
        from yani_engine.core.planner import WavePlanner

        orch = self._orch

        # ----------------------------------------------------------------
        # Pre-wave: review any orphaned .tmp files from a previous run
        # ----------------------------------------------------------------
        await OrphanRecoveryScanner().run(unattended=True)
        existing_tmps = set(glob.glob(".yani/tmp/*.tmp"))
        if existing_tmps:
            print(
                f"Found {len(existing_tmps)} unreviewed files from a previous run. "
                "Starting review..."
            )
            await batch_diff_review(list(existing_tmps))

        # ----------------------------------------------------------------
        # Read max_parallel_tasks from memory.md Config
        # ----------------------------------------------------------------
        max_parallel = 0
        try:
            async with _MEMORY_MUTEX:
                async with get_registry_lock():
                    with open("memory.md", "r", encoding="utf-8") as f:
                        mem_content = f.read()
            config_start, config_end = ASTMemoryMapper.locate_heading_block(
                mem_content, "##", "Config"
            )
            if config_start != -1:
                for line in mem_content.splitlines()[config_start:config_end]:
                    if "- max_parallel_tasks:" in line:
                        max_parallel = int(line.split(":")[1].strip())
        except Exception:
            pass

        wave_index = 0
        planner = WavePlanner(
            start_at_index=config.start_at_index,
            mcp_sessions=orch.mcp_sessions,
        )

        # ----------------------------------------------------------------
        # Main wave loop
        # ----------------------------------------------------------------
        while True:
            waves = await planner.get_pending_waves()
            if not waves:
                if wave_index == 0:
                    print("No pending tasks to execute.")
                    # Detect ghosted tasks from a manual kill
                    state = TaskRegistryState()
                    tasks_dict = await state.load_tasks()
                    stuck = [
                        t_id
                        for t_id, t in tasks_dict.items()
                        if t["status"] in ["in_progress", "interrupted"]
                    ]
                    if stuck:
                        print(
                            f"⚠ Found tasks stuck in 'in_progress' from a previous aborted run: "
                            f"{', '.join(stuck)}"
                        )
                        print("Run '/yani-engine resume' to safely clear the locks and execute them.")
                break

            wave = waves[0]
            wave_index += 1
            wave_i = wave_index - 1

            print(f"Starting execution wave {wave_index} with {len(wave)} tasks...")
            before_tmps = set(glob.glob(".yani/tmp/*.tmp"))

            try:
                await self._run_wave(wave, wave_i, len(waves), max_parallel)
            except BudgetExhaustedException:
                await orch._graceful_shutdown()
                break

            after_tmps = set(glob.glob(".yani/tmp/*.tmp"))
            wave_tmps = list(after_tmps - before_tmps)
            if wave_tmps:
                await batch_diff_review(wave_tmps)

    # ------------------------------------------------------------------
    # Internal: run a single wave under a Rich progress bar
    # ------------------------------------------------------------------

    async def _run_wave(
        self,
        wave: list,
        wave_i: int,
        total_waves: int,
        max_parallel: int,
    ) -> None:
        """
        Dispatches all tasks in a single wave through a bounded worker pool.
        Raises BudgetExhaustedException if budget is hit mid-wave.
        """
        from rich.progress import (
            Progress,
            SpinnerColumn,
            TextColumn,
            BarColumn,
            TaskProgressColumn,
        )
        from rich.console import Console

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=Console(force_terminal=True),
        ) as progress:
            wave_task = progress.add_task(
                f"[cyan]Executing Wave {wave_i + 1}/{total_waves}...",
                total=len(wave),
            )

            queue: asyncio.Queue = asyncio.Queue()
            for t in wave:
                queue.put_nowait(t)

            safe_parallel = 3 if max_parallel <= 0 else max_parallel
            num_workers = min(safe_parallel, len(wave))

            workers = [
                asyncio.create_task(
                    self._worker(f"w{i}", queue, progress, wave_task)
                )
                for i in range(num_workers)
            ]
            done, pending = await asyncio.wait(workers, return_when=asyncio.FIRST_EXCEPTION)

            for p in pending:
                p.cancel()

            for d in done:
                exc = d.exception()
                if exc is not None:
                    raise exc

    # ------------------------------------------------------------------
    # Internal: single worker coroutine (previously a closure)
    # ------------------------------------------------------------------

    async def _worker(
        self,
        worker_id: str,
        queue: asyncio.Queue,
        progress,
        wave_task,
    ) -> None:
        """
        Drains the queue, executing one task at a time.

        Raises BudgetExhaustedException to terminate all sibling workers
        via asyncio.wait(FIRST_EXCEPTION).
        """
        from yani_engine.core.orchestrator import BudgetExhaustedException

        orch = self._orch

        while True:
            try:
                t = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            task_id: str = t["id"]
            task_title: str = t.get("title", "")

            try:
                orch.budget_manager.check_and_harvest()
            except BudgetExhaustedException:
                queue.task_done()
                # Drain queue so other workers exit cleanly
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()
                raise

            progress.console.print(
                f"  [bold yellow]🔄 [IN_PROGRESS][/bold yellow] "
                f"[cyan]{task_id}[/cyan]: {task_title}"
            )

            try:
                await orch.execute_task(task_id, task_title, worker_id=worker_id)
                progress.console.print(
                    f"  [bold green]✅ [AWAITING_REVIEW][/bold green] "
                    f"[cyan]{task_id}[/cyan]: {task_title}"
                )
            except BudgetExhaustedException:
                progress.console.print(
                    f"  [bold magenta]⏸ [INTERRUPTED][/bold magenta] "
                    f"[cyan]{task_id}[/cyan]: Budget exhausted"
                )
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()
                raise
            except Exception as e:
                progress.console.print(
                    f"  [bold red]❌ [ERROR][/bold red] [cyan]{task_id}[/cyan]: {e}"
                )
                await update_task_registry_row(task_id, "error")
                await flush_task_registry()
            finally:
                progress.advance(wave_task)
                queue.task_done()
                await flush_task_registry()

        # Per-worker sandbox teardown (runs once after the task loop exits)
        sandbox_mode = getattr(orch, "sandbox_mode", "native")
        if sandbox_mode not in ["native"] and not sandbox_mode.startswith("compose:"):
            from yani_engine.core.sandbox import _teardown_warm_sandbox
            await _teardown_warm_sandbox(worker_id)
