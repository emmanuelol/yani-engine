"""
llm_handlers.py — LLM Bootstrapping Command Handlers (start, iterate).

Extracted from LLMOrchestrator.run() branches for 'start' and 'iterate'.

Responsibilities:
  - 'start': Initialize memory.md from template, then run the planning
    agent loop to populate Project Goal and Task Registry.
  - 'iterate': Validate prompt length, optionally enrich with Context7,
    then dispatch a bounded LLM loop to generate new task batches.

Dependency injection:
  Both handlers receive `orchestrator: LLMOrchestrator` which provides:
    - provider (for create_chat_session)
    - model (set by run() preamble before dispatch)
    - plugin_root (for template resolution)
    - _get_tools_for_command, _get_system_instructions, _run_with_tools
    - mcp_sessions (for context7 enrichment)
    - budget_manager

Token clamping:
  iterate hard-caps at max_iterations=30 and at most 5 tasks per batch.
  This matches the original inline constraint in LLMOrchestrator.run().
"""

from __future__ import annotations

import glob
import os
from typing import TYPE_CHECKING

from yani_engine.core.locks import _MEMORY_MUTEX, get_registry_lock
from yani_engine.core.review_ui import batch_diff_review

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator


async def handle_start(orchestrator: "LLMOrchestrator", args: list) -> None:
    """
    Bootstraps memory.md from the project template, then runs the
    planning agent loop to set the Project Goal and Task Registry.

    Expects orchestrator.model to be set by run() preamble (heavy tier).
    """
    from rich.console import Console
    from datetime import datetime

    if os.path.exists("memory.md"):
        print("Error: memory.md already exists. Run /yani-engine:resume to continue.")
        return

    print("Bootstrapping native memory.md state machine...")
    template_path = os.path.join(orchestrator.plugin_root, "templates", "memory-template.md")

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            init_content = f.read()

        init_content = init_content.replace("{{DATE}}", datetime.utcnow().strftime("%Y-%m-%d"))
        init_content = init_content.replace("{{PROJECT_GOAL}}", "Pending LLM analysis...")
        init_content = init_content.replace("{{SCOPE_ITEMS}}", "- Pending LLM analysis...")

        async with _MEMORY_MUTEX:
            async with get_registry_lock():
                with open("memory.md", "w", encoding="utf-8") as f:
                    f.write(init_content)
    except Exception as e:
        print(f"CRITICAL: Failed to bootstrap memory.md: {e}")
        return

    orchestrator.chat_session = await orchestrator.provider.create_chat_session(
        model_name=orchestrator.model,
        tools=orchestrator._get_tools_for_command("start"),
    )

    sys_inst = await orchestrator.prompt_builder._get_system_instructions("start")
    payload = (
        f"{sys_inst}\n\nUSER DIRECTIVE: Execute the `start` command with arguments {args}. "
        "Follow your COMMAND SPECIFIC INSTRUCTIONS strictly."
    )

    console = Console()
    with console.status("[bold cyan]Running start agent...", spinner="dots") as status:
        try:
            response = await orchestrator.agent_runner._run_with_tools(
                orchestrator.chat_session, payload, orchestrator.provider, status=status
            )
        except Exception as e:
            print(f"\n[bold red]Agent execution aborted: {e}[/bold red]")
            return

    # Review any diff-gate orphans generated during start
    existing_tmps = set(glob.glob(".yani/tmp/*.tmp"))
    if existing_tmps:
        print(f"\nFound {len(existing_tmps)} unreviewed files from initialization. Starting review...")
        await batch_diff_review(list(existing_tmps))

    final_text = getattr(response, "text", "") if hasattr(response, "text") else str(response)
    print(final_text)


async def handle_iterate(orchestrator: "LLMOrchestrator", args: list) -> None:
    """
    Validates the prompt, optionally enriches context via Context7,
    and dispatches a bounded LLM loop to generate a new task batch.

    Token clamping: max_iterations=30, at most 5 tasks per call.
    Expects orchestrator.model to be set by run() preamble (heavy tier).
    """
    from rich.console import Console

    enrich_flag = any(
        arg.startswith("--enrich") and "true" in arg.lower() for arg in args
    )
    prompt_text = " ".join([a for a in args if not a.startswith("--enrich")]).strip()

    if len(prompt_text) < 20:
        print(
            "Error: /yani-engine iterate requires a detailed prompt (min 20 chars). "
            "Vague prompts cause hallucinated task loops."
        )
        return

    orchestrator.chat_session = await orchestrator.provider.create_chat_session(
        model_name=getattr(orchestrator, "model", None) or __import__(
            "yani_engine.core.config", fromlist=["config"]
        ).config.model,
        tools=orchestrator._get_tools_for_command("iterate"),
    )

    sys_inst = await orchestrator.prompt_builder._get_system_instructions("iterate")

    enrich_context = ""
    if enrich_flag and "context7" in orchestrator.mcp_sessions:
        enrich_context = (
            "\n# ENRICHED CONTEXT\n"
            + await orchestrator.mcp_sessions["context7"].call_tool(
                "query-docs", arguments={"query": prompt_text}
            )
        )

    payload = (
        f"{sys_inst}\n\n"
        f"USER DIRECTIVE: Execute the `iterate` command with the following instruction: "
        f"{prompt_text}\n{enrich_context}\n\n"
        "STRICT LIMIT: You may call `register_task_batch` at most ONE time, "
        "and you may schedule at most 5 tasks total for this iteration."
    )

    console = Console()
    with console.status("[bold cyan]Running iterate agent...", spinner="dots") as status:
        try:
            response = await orchestrator.agent_runner._run_with_tools(
                orchestrator.chat_session,
                payload,
                orchestrator.provider,
                status=status,
                max_iterations=30,
            )
        except Exception as e:
            print(f"\n[bold red]Agent execution aborted: {e}[/bold red]")
            return

    final_text = getattr(response, "text", "") if hasattr(response, "text") else str(response)
    print(final_text)
