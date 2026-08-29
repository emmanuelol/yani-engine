"""
mcp_manager.py — MCP Client Lifecycle Management.

Extracted from LLMOrchestrator.connect_mcp() to decouple process
spawning and RPC bridging from the core orchestration engine.

Design decision:
  _create_mcp_wrapper() remains on LLMOrchestrator to preserve the
  contract tested by test_mapping.py (cli._create_mcp_wrapper(...)).
  A shim on LLMOrchestrator delegates to this module's standalone
  function, keeping the public API stable while isolating the logic.

Circuit-breaking:
  Each server connection is independently try/except-guarded. A hung
  npx process is handled by the underlying stdio_client timeout; the
  orchestrator boot sequence continues in degraded mode rather than
  stalling entirely.

Ownership:
  The exit_stack passed in is owned by LLMOrchestrator. MCP transports
  are registered on it so they are closed when the orchestrator's
  AsyncExitStack is closed at the end of run().
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
from typing import TYPE_CHECKING

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop
    from contextlib import AsyncExitStack
    from yani_engine.core.orchestrator import LLMOrchestrator


def create_mcp_wrapper(server_name: str, tool, mcp_sessions: dict, mcp_locks: dict, config):
    """
    Build a type-annotated async wrapper around an MCP tool.

    The wrapper is callable as a plain Python async function that the
    LLM SDK sees as a first-class tool. It enforces a 45-second RPC
    timeout and uses a per-server semaphore to prevent thundering-herd
    against the MCP subprocess.

    Args:
        server_name: MCP server key (e.g., "codegraph", "context7").
        tool:        The raw MCP tool descriptor (has .name, .inputSchema,
                     .description).
        mcp_sessions: Shared session dict owned by the orchestrator.
        mcp_locks:   Shared semaphore dict owned by the orchestrator.
        config:      AppConfig instance for max_parallel_tasks.

    Returns:
        An async callable with injected __name__, __signature__,
        __annotations__, and __doc__.
    """
    async def mcp_wrapper(**kwargs):
        sem = mcp_locks.setdefault(
            server_name,
            asyncio.Semaphore(getattr(config, "max_parallel_tasks", 3) or 3),
        )
        async with sem:
            session = mcp_sessions[server_name]
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool.name, arguments=kwargs), timeout=45.0
                )
                return "\n".join([x.text for x in result.content if hasattr(x, "text")])
            except asyncio.TimeoutError:
                return (
                    f"Error: Tool '{tool.name}' timed out after 45 seconds. "
                    "The query was too broad or the server hung. Narrow your target symbol."
                )

    # 1. Strip slashes and hyphens for Gemini compatibility
    safe_name = tool.name.replace("-", "_").replace("/", "_")
    final_name = safe_name if safe_name.startswith(server_name) else f"{server_name}_{safe_name}"

    # 2. Hard-bind both name attributes so the SDK caching doesn't overwrite it
    mcp_wrapper.__name__ = final_name
    mcp_wrapper.__qualname__ = final_name

    # 3. Dynamic Signature Injection — maps JSON Schema types to Python annotations
    params = []
    annotations: dict = {}

    if hasattr(tool, "inputSchema") and tool.inputSchema and "properties" in tool.inputSchema:
        for prop_name, prop_schema in tool.inputSchema["properties"].items():
            ptype = str
            if prop_schema.get("type") == "integer":
                ptype = int
            elif prop_schema.get("type") == "boolean":
                ptype = bool
            elif prop_schema.get("type") == "number":
                ptype = float
            elif prop_schema.get("type") == "array":
                ptype = list

            is_req = prop_name in tool.inputSchema.get("required", [])
            default = inspect.Parameter.empty if is_req else None

            annotations[prop_name] = ptype
            params.append(
                inspect.Parameter(
                    name=prop_name,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    annotation=ptype,
                    default=default,
                )
            )

    mcp_wrapper.__signature__ = inspect.Signature(parameters=params)
    mcp_wrapper.__annotations__ = annotations

    # 4. Guard: Limit tool descriptions to prevent token window exhaustion
    doc_str = getattr(tool, "description", "")
    if doc_str and len(doc_str) > 1024:
        doc_str = doc_str[:1021] + "..."
    mcp_wrapper.__doc__ = doc_str

    return mcp_wrapper


async def connect_mcp(
    orchestrator: "LLMOrchestrator",
) -> None:
    """
    Initialise all MCP server connections and register wrappers on
    orchestrator.gemini_tools and orchestrator.mcp_sessions.

    Each server is independently guarded: failure to connect one does
    not abort the others. The orchestrator continues in degraded mode
    with the surviving servers.

    Args:
        orchestrator: The active LLMOrchestrator. Its exit_stack,
                      gemini_tools, mcp_sessions, and mcp_locks are
                      mutated in place.
    """
    from yani_engine.core.config import config as _config

    exit_stack = orchestrator.exit_stack
    gemini_tools = orchestrator.gemini_tools
    mcp_sessions = orchestrator.mcp_sessions
    mcp_locks = orchestrator.mcp_locks

    def _make_wrapper(server_name, tool):
        return create_mcp_wrapper(server_name, tool, mcp_sessions, mcp_locks, _config)

    # ------------------------------------------------------------------
    # 1. CodeGraph MCP
    # ------------------------------------------------------------------
    try:
        if not os.path.exists(".codegraph"):
            os.makedirs(".codegraph", exist_ok=True)
            print("Initializing CodeGraph index...", file=sys.stderr)
            import subprocess
            await asyncio.to_thread(
                subprocess.run,
                ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"],
                check=True,
            )

        codegraph_params = StdioServerParameters(
            command="npx",
            args=["--yes", "--quiet", "--package=@colbymchenry/codegraph", "codegraph", "serve", "--mcp"],
        )
        codegraph_transport, codegraph_stream = await exit_stack.enter_async_context(
            stdio_client(codegraph_params)
        )
        codegraph_session = await exit_stack.enter_async_context(
            ClientSession(codegraph_transport, codegraph_stream)
        )
        await codegraph_session.initialize()
        cg_tools = await codegraph_session.list_tools()

        for tool in cg_tools.tools:
            gemini_tools.append(_make_wrapper("codegraph", tool))
        mcp_sessions["codegraph"] = codegraph_session
    except Exception as e:
        print(f"CodeGraph MCP degraded: {e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # 2. Context7 MCP
    # ------------------------------------------------------------------
    try:
        context7_params = StdioServerParameters(
            command="npx",
            args=["--yes", "--quiet", "@upstash/context7-mcp"],
        )
        context7_transport, context7_stream = await exit_stack.enter_async_context(
            stdio_client(context7_params)
        )
        context7_session = await exit_stack.enter_async_context(
            ClientSession(context7_transport, context7_stream)
        )
        await context7_session.initialize()
        c7_tools = await context7_session.list_tools()

        for tool in c7_tools.tools:
            gemini_tools.append(_make_wrapper("context7", tool))
        mcp_sessions["context7"] = context7_session
    except Exception as e:
        print(f"Context7 MCP degraded: {e}", file=sys.stderr)

    # 3. Set codegraph health flag for tool filtering
    existing_names = [getattr(t, "__name__", "") for t in gemini_tools]
    orchestrator.is_codegraph_active = any(
        name.startswith("codegraph_") for name in existing_names
    )
