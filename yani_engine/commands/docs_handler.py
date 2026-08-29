"""
docs_handler.py — Smart Documentation Updater command handler.

Extracted from LLMOrchestrator.run() "update-docs" branch.

Responsibilities:
  - Parse --docs / --dry-run / --enrich CLI args
  - Read changed files from Git log since last_docs_update
  - Extract explicit AST symbol bindings from Markdown wikilinks and
    HTML comment annotations
  - Invert-search each symbol through CodeGraph for staleness
  - Queue surgical patch tasks in the Task Registry
  - Stamp last_docs_update in memory.md Config block

I/O contract:
  - All subprocess.run (git log, codegraph) are wrapped in
    asyncio.to_thread() to prevent event loop starvation.
  - memory.md writes are guarded by _MEMORY_MUTEX + get_registry_lock().
"""

import os
import re
import glob
import asyncio
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

from yani_engine.core.locks import _MEMORY_MUTEX, get_registry_lock
from yani_engine.core.state import ASTMemoryMapper, register_task_batch
from yani_engine.core.config import config

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator


async def handle_update_docs(orchestrator: "LLMOrchestrator", args: list) -> None:
    """
    Drives the update-docs command end-to-end.

    Args:
        orchestrator: The active LLMOrchestrator instance (used only to
                      access mcp_sessions for CodeGraph queries).
        args:         Raw CLI argument list forwarded from run().
    """
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import Prompt

    console = Console()

    # ------------------------------------------------------------------
    # 1. Parse Args
    # ------------------------------------------------------------------
    dry_run = "--dry-run" in args
    enrich = "--enrich" in args
    docs_path = None

    for i, arg in enumerate(args):
        if arg.startswith("--docs="):
            docs_path = arg.split("=")[1]
        elif arg == "--docs" and i + 1 < len(args):
            docs_path = args[i + 1]

    if not os.path.exists("memory.md"):
        print("Error: memory.md not found. Run /yani-engine:start to initialize.")
        return

    # ------------------------------------------------------------------
    # 2. Read memory.md once under full lock
    # ------------------------------------------------------------------
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            with open("memory.md", "r", encoding="utf-8") as f:
                mem_content = f.read()

    # ------------------------------------------------------------------
    # 3. Resolve docs_path from Config if not given on CLI
    # ------------------------------------------------------------------
    if not docs_path:
        conf_start, conf_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
        if conf_start != -1:
            for line in mem_content.splitlines()[conf_start:conf_end]:
                if "- docs_path:" in line:
                    docs_path = line.split(":", 1)[1].strip()

    if not docs_path or not os.path.isdir(docs_path):
        print(f"Error: valid docs path not found ('{docs_path}'). Provide --docs <path>.")
        return

    # ------------------------------------------------------------------
    # 4. Read last_docs_update from Config
    # ------------------------------------------------------------------
    last_docs_update = None
    conf_start, conf_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
    if conf_start != -1:
        for line in mem_content.splitlines()[conf_start:conf_end]:
            if "- last_docs_update:" in line and "null" not in line and "never" not in line:
                last_docs_update = line.split(":", 1)[1].strip()

    # ------------------------------------------------------------------
    # 5. Get changed files from Git (non-blocking)
    # ------------------------------------------------------------------
    changed_files: list[str] = []
    if last_docs_update:
        try:
            git_proc = await asyncio.to_thread(
                subprocess.run,
                ["git", "log", "--name-only", "--pretty=format:", f"--since={last_docs_update}"],
                capture_output=True,
                text=True,
            )
            changed_files = [f.strip() for f in git_proc.stdout.splitlines() if f.strip()]
        except Exception:
            pass

    console.print(f"[cyan]Scanning '{docs_path}' for explicit AST bindings...[/cyan]")

    # ------------------------------------------------------------------
    # 6. Explicit AST Extraction
    #    Wikilinks:     [[SymbolName]] or [[SymbolName|Display]]
    #    HTML comments: <!-- ast-symbol: SymbolName -->
    # ------------------------------------------------------------------
    wikilink_pattern = re.compile(r'\[\[([^\|\]]+)(?:\|[^\]]+)?\]\]')
    html_comment_pattern = re.compile(r'<!--\s*ast-symbol:\s*([^\s>]+)\s*-->')

    doc_files = glob.glob(os.path.join(docs_path, "**/*.md"), recursive=True)
    if not doc_files:
        console.print(f"[yellow]Warning: No markdown files found in {docs_path}.[/yellow]")
        return

    tasks_to_create: list[dict] = []

    # ------------------------------------------------------------------
    # 7. Inverted Search & Delta Analysis (CodeGraph per symbol)
    # ------------------------------------------------------------------
    with console.status("[bold yellow]Inverting search against CodeGraph AST...", spinner="dots"):
        for doc_file in doc_files:
            with open(doc_file, "r", encoding="utf-8") as df:
                doc_content = df.read()

            symbols = set(
                wikilink_pattern.findall(doc_content)
                + html_comment_pattern.findall(doc_content)
            )

            needs_update = False
            reasons: list[str] = []

            if enrich and len(doc_content.splitlines()) <= 5:
                needs_update = True
                reasons.append("Sparse document (enrichment candidate)")

            for sym in symbols:
                try:
                    cg_proc = await asyncio.to_thread(
                        subprocess.run,
                        ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "search", sym],
                        capture_output=True,
                        text=True,
                    )
                    cg_out = cg_proc.stdout

                    if "No results" in cg_out or not cg_out.strip():
                        needs_update = True
                        reasons.append(f"Symbol '{sym}' is dead/missing")
                    elif not last_docs_update or any(cf in cg_out for cf in changed_files):
                        needs_update = True
                        reasons.append(f"Symbol '{sym}' source file modified")
                except Exception:
                    pass

            if needs_update:
                tasks_to_create.append({"file": doc_file, "reasons": list(set(reasons))})

    # ------------------------------------------------------------------
    # 8. Early exit if nothing to update
    # ------------------------------------------------------------------
    if not tasks_to_create:
        console.print(
            "[green]Documentation is already up to date. "
            "No dead symbols or modified sources detected.[/green]"
        )
        return

    # ------------------------------------------------------------------
    # 9. Render proposal table
    # ------------------------------------------------------------------
    table = Table(title="Proposed Documentation Updates")
    table.add_column("Document", style="cyan")
    table.add_column("Reason", style="yellow")
    for t in tasks_to_create:
        table.add_row(t["file"], ", ".join(t["reasons"]))
    console.print(table)

    if dry_run:
        console.print("\n[yellow]Dry run — no files modified. Run without --dry-run to apply.[/yellow]")
        return

    # ------------------------------------------------------------------
    # 10. Interactive approval gate
    # ------------------------------------------------------------------
    if config.verbose or not getattr(config, "non_interactive", False):
        choice = Prompt.ask(
            "Queue these surgical patches into the Task Registry? [Y/N]",
            choices=["Y", "N"],
            default="Y",
        )
    else:
        console.print("[green]Auto-approving surgical patch queue (run interactively to review)[/green]")
        choice = "Y"

    if choice == "N":
        console.print("[yellow]Update cancelled.[/yellow]")
        return

    # ------------------------------------------------------------------
    # 11. Task Generation & Handoff
    # ------------------------------------------------------------------
    console.print("\n[cyan]Queueing tasks...[/cyan]")
    tasks_batch = [
        {
            "title": f"Update docs: {os.path.basename(t['file'])}",
            "task_type": "change",
            "deps": "none",
            "description": (
                f"Surgically patch {t['file']} to resolve: {', '.join(t['reasons'])}. "
                "STRICTLY preserve human rationale, Mermaid diagrams, and tables."
            ),
            "outputs": t["file"],
            "success_criteria": "TBD",
            "estimated_effort": "small",
            "codegraph_impact": "—",
        }
        for t in tasks_to_create
    ]
    if tasks_batch:
        res = await register_task_batch(tasks_batch)
        console.print(f"[dim]{res}[/dim]")

    # ------------------------------------------------------------------
    # 12. Stamp last_docs_update in memory.md Config block (atomic write)
    # ------------------------------------------------------------------
    now_iso = datetime.utcnow().isoformat() + "Z"
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            with open("memory.md", "r", encoding="utf-8") as f:
                fresh_mem = f.read()
            fresh_mem = re.sub(r"- last_docs_update:.*", f"- last_docs_update: {now_iso}", fresh_mem)
            with open("memory.md", "w", encoding="utf-8") as f:
                f.write(fresh_mem)

    console.print(
        "\n[bold green]Tasks successfully queued! "
        "Run /yani-engine:execute to trigger the LLM patch wave.[/bold green]"
    )
