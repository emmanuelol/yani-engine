"""
resume_handler.py — Resume Command Handler.

Extracted from LLMOrchestrator.run() resume branch.

Contract:
  handle_resume() returns either None (terminal — command was fully
  handled) or the string "execute" (signal to the caller that it should
  re-dispatch to the execute wave engine after lock clearing).

I/O:
  - os.makedirs and file writes inside checkpoint restore are wrapped
    in asyncio.to_thread() to prevent event loop starvation.
  - open(chk_path, "r") stays synchronous: read-only, single JSON blob,
    no concurrent writers possible at this point in the flow.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

from yani_engine.core.config import config
from yani_engine.core.state import (
    OrphanRecoveryScanner,
    TaskRegistryState,
    flush_task_registry,
    update_task_registry_row,
)

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator


async def handle_resume(
    orchestrator: "LLMOrchestrator", args: list
) -> str | None:
    """Scan for interrupted tasks, offer recovery options, then signal execute.

    Returns:
        "execute"  — caller should hand off to WaveExecutor immediately.
        None       — command was fully handled (no tasks, rollback, or skip).
    """
    from rich.console import Console
    from rich.prompt import Prompt

    await OrphanRecoveryScanner().run()

    state = TaskRegistryState()
    tasks = await state.load_tasks()

    interrupted = [
        t_id
        for t_id, t in tasks.items()
        if t["status"] in ["interrupted", "in_progress", "error"]
    ]

    if not interrupted:
        print("\nNo interrupted tasks or stale locks found. Run /yani-engine:execute to process pending tasks.")
        return None

    console = Console()
    console.print(
        f"\n[bold yellow]Found interrupted or stale tasks: {', '.join(interrupted)}[/bold yellow]"
    )

    # Verbose gate: prevent agent lockups on headless execution
    if config.verbose:
        choice = Prompt.ask(
            "How would you like to handle them? [R(esume)/B(Rollback)/S(Skip)]",
            choices=["R", "B", "S"],
            default="R",
        )
    else:
        console.print(
            "[green]Auto-selecting 'Resume' for interrupted tasks "
            "(run with -v for interactive options)[/green]"
        )
        choice = "R"

    if choice == "B":
        for t_id in interrupted:
            await update_task_registry_row(t_id, "pending")
        await flush_task_registry()
        console.print(
            "[yellow]Tasks demoted to pending. "
            "Please run /yani-engine:rollback to revert file changes manually.[/yellow]"
        )
        return None

    if choice == "S":
        for t_id in interrupted:
            await update_task_registry_row(t_id, "deferred")
        await flush_task_registry()
        console.print("[green]Tasks deferred.[/green]")
        return None

    # choice == "R" — restore from checkpoints and chain into execute
    for t_id in interrupted:
        task_data = tasks.get(t_id, {})
        checkpoint_id = task_data.get("checkpoint", "none").strip()

        if checkpoint_id != "none":
            chk_path = os.path.join(".yani", "checkpoints", f"{checkpoint_id}.json")
            if os.path.exists(chk_path):
                with open(chk_path, "r") as f:
                    chk_data = json.load(f)
                for file_path, file_content in chk_data.get("files", {}).items():
                    await asyncio.to_thread(
                        os.makedirs,
                        os.path.dirname(os.path.abspath(file_path)),
                        exist_ok=True,
                    )

                    def _write(fp=file_path, fc=file_content):
                        with open(fp, "w") as tf:
                            tf.write(fc)

                    await asyncio.to_thread(_write)
                console.print(
                    f"[green]Restored file state from checkpoint {checkpoint_id} for {t_id}[/green]"
                )
            else:
                console.print(
                    f"[yellow]Checkpoint {checkpoint_id} referenced by {t_id} "
                    "not found on disk. Resetting task.[/yellow]"
                )

        await update_task_registry_row(t_id, "pending", "—")

    await flush_task_registry()

    console.print(
        "[green]Locks cleared and checkpoints restored. "
        "Handing off to execution engine...[/green]"
    )

    # Signal the caller to re-dispatch as "execute"
    return "execute"
