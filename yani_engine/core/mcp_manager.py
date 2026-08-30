"""
mcp_manager.py — MCP Client Lifecycle Management.

Extracted from LLMOrchestrator.connect_mcp() to decouple process
spawning and RPC bridging from the core orchestration engine.

Design decision:
  create_mcp_wrapper() is a standalone pure function in this module.
  LLMOrchestrator no longer maintains legacy shims for tool wrapping.

Circuit-breaking:
  Each server connection is independently guarded by a file-backed
  PersistentCircuitBreaker and strict timeout boundaries on both
  subprocess execution (15s) and JSON-RPC handshakes (10s).
  If a server repeatedly fails or times out, the circuit trips to OPEN,
  allowing subsequent CLI runs to boot instantly in degraded mode
  without suffering repeated connection penalties.

Ownership:
  The exit_stack passed in is owned by LLMOrchestrator. MCP transports
  are registered on it so they are closed when the orchestrator's
  AsyncExitStack is closed at the end of run().
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop
    from contextlib import AsyncExitStack
    from yani_engine.core.orchestrator import LLMOrchestrator


class PersistentCircuitBreaker:
    """File-backed circuit breaker for ephemeral CLI runs."""

    def __init__(
        self,
        name: str,
        threshold: int = 2,
        recovery_window: int = 300,
        state_dir: str = ".yani",
    ) -> None:
        self.name = name
        self.threshold = threshold
        self.recovery_window = recovery_window
        self.state_file = Path(state_dir) / f"mcp_cb_{name}.json"

    def _read_state(self) -> dict:
        if not self.state_file.exists():
            return {"failures": 0, "last_failure": 0.0}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {"failures": 0, "last_failure": 0.0}

    def _write_state(self, state: dict) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.state_file.with_suffix(f".tmp.{os.getpid()}")
            temp_file.write_text(json.dumps(state), encoding="utf-8")
            os.replace(temp_file, self.state_file)
        except Exception:
            pass

    def is_open(self) -> bool:
        state = self._read_state()
        if state.get("failures", 0) >= self.threshold:
            if time.time() - state.get("last_failure", 0.0) < self.recovery_window:
                return True
            else:
                # Half-open: reset to threshold - 1 so single failure trips again
                self._write_state(
                    {"failures": self.threshold - 1, "last_failure": time.time()}
                )
                return False
        return False

    def record_failure(self) -> None:
        state = self._read_state()
        state["failures"] = state.get("failures", 0) + 1
        state["last_failure"] = time.time()
        self._write_state(state)

    def record_success(self) -> None:
        try:
            if self.state_file.exists():
                self.state_file.unlink()
        except Exception:
            pass


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

    Each server is independently circuit-breaker protected and timeout-bounded:
    - Subprocess initialization: timeout=15.0s
    - stdio transport and session initialization: timeout=10.0s
    - list_tools RPC: timeout=10.0s

    Failures trip the PersistentCircuitBreaker to prevent repeated stalls
    across ephemeral CLI runs.

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
    cg_cb = PersistentCircuitBreaker("codegraph")
    if not cg_cb.is_open():
        try:
            if not os.path.exists(".codegraph/codegraph.json"):
                os.makedirs(".codegraph", exist_ok=True)
                print("Initializing CodeGraph index...", file=sys.stderr)
                await asyncio.to_thread(
                    subprocess.run,
                    ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"],
                    check=True,
                    timeout=15.0,
                )

            codegraph_params = StdioServerParameters(
                command="npx",
                args=["--yes", "--quiet", "--package=@colbymchenry/codegraph", "codegraph", "serve", "--mcp"],
            )
            codegraph_transport, codegraph_stream = await asyncio.wait_for(
                exit_stack.enter_async_context(stdio_client(codegraph_params)),
                timeout=10.0,
            )
            codegraph_session = await exit_stack.enter_async_context(
                ClientSession(codegraph_transport, codegraph_stream)
            )
            await asyncio.wait_for(codegraph_session.initialize(), timeout=10.0)
            cg_tools = await asyncio.wait_for(codegraph_session.list_tools(), timeout=10.0)

            for tool in cg_tools.tools:
                gemini_tools.append(_make_wrapper("codegraph", tool))
            mcp_sessions["codegraph"] = codegraph_session
            cg_cb.record_success()
        except subprocess.TimeoutExpired:
            print("CodeGraph init timed out (npx stalled).", file=sys.stderr)
            cg_cb.record_failure()
        except asyncio.TimeoutError:
            print("CodeGraph RPC handshake timed out.", file=sys.stderr)
            cg_cb.record_failure()
        except Exception as e:
            print(f"CodeGraph MCP degraded: {e}", file=sys.stderr)
            cg_cb.record_failure()
    else:
        print("CodeGraph MCP Circuit Breaker OPEN: Skipping connection.", file=sys.stderr)

    # ------------------------------------------------------------------
    # 2. Context7 MCP
    # ------------------------------------------------------------------
    c7_cb = PersistentCircuitBreaker("context7")
    if not c7_cb.is_open():
        try:
            context7_params = StdioServerParameters(
                command="npx",
                args=["--yes", "--quiet", "@upstash/context7-mcp"],
            )
            context7_transport, context7_stream = await asyncio.wait_for(
                exit_stack.enter_async_context(stdio_client(context7_params)),
                timeout=10.0,
            )
            context7_session = await exit_stack.enter_async_context(
                ClientSession(context7_transport, context7_stream)
            )
            await asyncio.wait_for(context7_session.initialize(), timeout=10.0)
            c7_tools = await asyncio.wait_for(context7_session.list_tools(), timeout=10.0)

            for tool in c7_tools.tools:
                gemini_tools.append(_make_wrapper("context7", tool))
            mcp_sessions["context7"] = context7_session
            c7_cb.record_success()
        except asyncio.TimeoutError:
            print("Context7 RPC handshake timed out.", file=sys.stderr)
            c7_cb.record_failure()
        except Exception as e:
            print(f"Context7 MCP degraded: {e}", file=sys.stderr)
            c7_cb.record_failure()
    else:
        print("Context7 MCP Circuit Breaker OPEN: Skipping connection.", file=sys.stderr)

    # 3. Set codegraph health flag for tool filtering
    existing_names = [getattr(t, "__name__", "") for t in gemini_tools]
    orchestrator.is_codegraph_active = any(
        name.startswith("codegraph_") for name in existing_names
    )
