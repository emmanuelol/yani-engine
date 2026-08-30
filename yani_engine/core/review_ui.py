"""
review_ui.py — Stateless Diff-Gate UI module.

Extracted from LLMOrchestrator.batch_diff_review to decouple terminal
rendering, VS Code subprocess orchestration, and user prompt logic from
the core execution engine.

I/O contract: synchronous file operations (open, shutil, os.remove) are
preserved verbatim from the original. asyncio.to_thread() wrapping is
deferred to Phase 2 (async I/O hardening) to prevent untraceable
regressions during structural extraction.
"""

import os
import sys
import subprocess
import shutil
import difflib
import asyncio
import re
import datetime

from yani_engine.core.config import config
from yani_engine.core.locks import _MEMORY_MUTEX, get_registry_lock
from yani_engine.core.state import (
    TaskRegistryState,
    ASTMemoryMapper,
    CheckpointManager,
    OrphanRecoveryScanner,
    update_task_registry_row,
    flush_task_registry,
    split_markdown_cells,
)


async def batch_diff_review(wave_tmp_files: list):
    """
    Stateless async function that drives the diff-gate UI.

    Renders diffs in VS Code (when available and verbose) and in the
    terminal, prompts the user for approval, then atomically applies or
    rolls back each file in wave_tmp_files.

    Args:
        wave_tmp_files: List of absolute/relative .tmp paths staged for
                        review, typically produced by a completed wave.
    """
    if not wave_tmp_files:
        return

    has_code = shutil.which("code") is not None

    # ------------------------------------------------------------------ #
    # Phase A: VS Code GUI diff (only when -v flag is set and code exists) #
    # ------------------------------------------------------------------ #
    if config.verbose and has_code:
        print("Opening proposed changes in VS Code for review...", file=sys.stderr)

        # Read memory.md once to build a target->task_id mapping
        task_mapping = {}
        if os.path.exists("memory.md"):
            async with _MEMORY_MUTEX:
                async with get_registry_lock():
                    with open("memory.md", "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip().startswith("|") and "---" not in line and "Timestamp" not in line:
                                parts = split_markdown_cells(line)
                                if len(parts) >= 5 and parts[4] == "planned":
                                    task_id, target = parts[1], parts[2]
                                    task_mapping[target] = task_id

        for tmp_path in wave_tmp_files:
            basename = os.path.basename(tmp_path)
            actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
            actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")

            # Deterministic rollback lookup (no glob wildcards -- Fix 2A)
            rollback_path = None
            task_id = task_mapping.get(actual_filename)
            if task_id:
                encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
                possible_rollback = os.path.join(".yani", "rollbacks", task_id, encoded_path)
                if os.path.exists(possible_rollback):
                    rollback_path = possible_rollback

            if rollback_path and os.path.exists(rollback_path):
                vscode_args = ["code", "--wait", "--diff", rollback_path, tmp_path]
            else:
                vscode_args = ["code", "--wait", "--diff", os.devnull, tmp_path]

            print(f"Opening diff in VS Code: {' '.join(vscode_args)}")
            await asyncio.to_thread(subprocess.run, vscode_args, check=False)

    # ------------------------------------------------------------------ #
    # Phase B: Terminal unified-diff (always shown as fallback)           #
    # ------------------------------------------------------------------ #
    from rich.syntax import Syntax
    from rich.console import Console

    console_diff = Console()
    for tmp_path in wave_tmp_files:
        basename = os.path.basename(tmp_path)
        actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
        actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")

        original_text = ""
        rollback_path = None
        task_id = None

        # Deterministic rollback lookup per file (no glob wildcards -- Fix 2B)
        if os.path.exists("memory.md"):
            async with _MEMORY_MUTEX:
                async with get_registry_lock():
                    with open("memory.md", "r", encoding="utf-8") as mem:
                        for line in mem:
                            if line.strip().startswith("|") and "---" not in line and "Timestamp" not in line:
                                parts = split_markdown_cells(line)
                                if (
                                    len(parts) >= 5
                                    and parts[4] == "planned"
                                    and parts[2] == actual_filename
                                ):
                                    task_id = parts[1]
                                    break

        if task_id:
            encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
            possible_rollback = os.path.join(".yani", "rollbacks", task_id, encoded_path)
            if os.path.exists(possible_rollback):
                rollback_path = possible_rollback

        if rollback_path and os.path.exists(rollback_path):
            with open(rollback_path, "r") as f:
                original_text = f.read()

        with open(tmp_path, "r") as f:
            new_text = f.read()

        diff = list(
            difflib.unified_diff(
                original_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{actual_filename}",
                tofile=f"b/{actual_filename}",
            )
        )
        if diff:
            diff_text = "".join(diff)
            syntax = Syntax(diff_text, "diff", theme="monokai")
            console_diff.print(f"\n[bold cyan]Diff for {actual_filename}:[/bold cyan]")
            console_diff.print(syntax)

    # ------------------------------------------------------------------ #
    # Phase C: User approval prompt                                        #
    # ------------------------------------------------------------------ #
    from rich.prompt import Prompt

    console = Console()
    if config.verbose:
        choice = await asyncio.to_thread(
            Prompt.ask,
            "Approve wave changes? [Y(all)/N(none)/S(select)]",
            choices=["Y", "N", "S"],
            default="Y",
        )
    else:
        console.print("[green]Auto-approving wave changes (run with -v to review)[/green]")
        choice = "Y"

    rejected_files: set = set()
    if choice == "S":
        sel = await asyncio.to_thread(
            Prompt.ask, "Enter filenames to reject (comma separated)"
        )
        rejected_files = {s.strip() for s in sel.split(",") if s.strip()}
    elif choice == "N":
        rejected_files = {os.path.basename(f) for f in wave_tmp_files}

    # ------------------------------------------------------------------ #
    # Phase D: Atomic apply or rollback per file                          #
    # ------------------------------------------------------------------ #
    _state = TaskRegistryState()  # instantiated for registry side-effects
    for tmp_path in wave_tmp_files:
        basename = os.path.basename(tmp_path)
        uuid_match = re.match(r"^[0-9a-f]{32}_(.+)$", basename)
        actual_filename = uuid_match.group(1) if uuid_match else basename
        actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")

        target_path = actual_filename
        task_id = None
        try:
            async with _MEMORY_MUTEX:
                async with get_registry_lock():
                    with open("memory.md", "r", encoding="utf-8") as f:
                        content = f.read()
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(
                content, "##", "Change Log"
            )
            if start_idx != -1:
                for line in content.splitlines()[start_idx + 1 : end_idx]:
                    if line.strip().startswith("|") and "---" not in line and "Timestamp" not in line:
                        parts = split_markdown_cells(line)
                        if (
                            len(parts) >= 5
                            and parts[4].strip() == "planned"
                            and parts[2].strip() == actual_filename
                        ):
                            target_path = parts[2].strip()
                            task_id = parts[1].strip()
                            break
        except Exception:
            pass

        if actual_filename in rejected_files or basename in rejected_files:
            # Rejection path: remove tmp and restore from rollback (Fix 2C)
            # All mutating I/O wrapped in to_thread() to avoid blocking event loop.
            if os.path.exists(tmp_path):
                await asyncio.to_thread(os.remove, tmp_path)

            encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
            possible_rollback = (
                os.path.join(".yani", "rollbacks", task_id, encoded_path)
                if task_id
                else None
            )

            if possible_rollback and os.path.exists(possible_rollback):
                await asyncio.to_thread(shutil.copy2, possible_rollback, target_path)
                console.print(
                    f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]"
                )
            elif os.path.exists(target_path):
                # Newly created file -- no rollback exists, safe to delete
                await asyncio.to_thread(os.remove, target_path)
                console.print(
                    f"[yellow]Rejected new file creation, deleted {actual_filename}[/yellow]"
                )

            if task_id:
                await update_task_registry_row(task_id, "pending")
                await flush_task_registry()
        else:
            # Approval path: atomic rename from .tmp to target
            if os.path.exists(tmp_path):
                await asyncio.to_thread(
                    os.makedirs,
                    os.path.dirname(os.path.abspath(target_path)),
                    exist_ok=True,
                )
                await CheckpointManager().atomic_rename_to_target(tmp_path, target_path)

            console.print(f"[green]Approved changes for {actual_filename}[/green]")
            if task_id:
                await update_task_registry_row(task_id, "completed")
                await flush_task_registry()
                await CheckpointManager().log_applied_change(
                    target_path,
                    {
                        "Task ID": task_id,
                        "Timestamp": datetime.datetime.now().isoformat(),
                    },
                )

    if rejected_files:
        await OrphanRecoveryScanner().run(True)
