"""
agent_loop.py — Core LLM Agent Loop.

Extracted from LLMOrchestrator to decouple the network transport layer
(exponential backoff, rate-limit retry) and the tool execution loop from
CLI dispatch and routing.

Responsibilities:
  - _send_message_with_backoff: retry wrapper with 429/500/503 handling
  - _run_with_tools: token-bounded tool execution loop with sliding-window
    history pruning, bleed-valve output truncation, and degraded-tool detection

Dependency injection:
  AgentRunner(orchestrator) holds a reference to the live LLMOrchestrator
  instance to access budget_manager, gemini_tools, and sandbox_mode.
  No state is copied or held locally — all mutations go through the
  orchestrator reference.

Usage:
  LLMOrchestrator.__init__ instantiates self.agent_runner = AgentRunner(self).
  Callers invoke orchestrator.agent_runner._run_with_tools(...).
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator


class AgentRunner:
    """Stateless LLM agent loop and network transport layer.

    Instantiated once per LLMOrchestrator and stored as
    orchestrator.agent_runner. All execution state lives on the
    orchestrator reference; AgentRunner holds no mutable state of its own.
    """

    def __init__(self, orchestrator: "LLMOrchestrator") -> None:
        self._o = orchestrator

    async def _send_message_with_backoff(self, chat_session, payload, active_provider):
        import random

        max_retries = 8
        base_delay = 15
        total_elapsed = 0
        max_total_wait = 600  # Hard cap: 10 minutes total backoff to survive heavy 429 throttling
        for attempt in range(max_retries):
            try:
                return await active_provider.send_message(chat_session, payload)
            except Exception as e:
                error_str = str(e)
                # FIX: Added "500", "INTERNAL", and "503" to the retry conditions
                if (
                    "429" in error_str
                    or "RESOURCE_EXHAUSTED" in error_str
                    or "Quota exceeded" in error_str
                    or "500" in error_str
                    or "INTERNAL" in error_str
                    or "503" in error_str
                ):
                    if attempt == max_retries - 1:
                        raise
                    match = re.search(r"retry in (\d+)s", error_str)
                    if match:
                        delay = int(match.group(1)) + random.uniform(2, 5)
                    else:
                        delay = base_delay * (1.5 ** attempt) + random.uniform(0, 5)
                    if total_elapsed + delay > max_total_wait:
                        raise RuntimeError(
                            f"Rate limit backoff exceeded {max_total_wait}s total wait "
                            f"({total_elapsed:.0f}s elapsed)"
                        )
                    print(
                        f"API Rate Limit/Internal Error hit. Task pausing for {delay:.1f}s "
                        f"before retry {attempt+1}/{max_retries}..."
                    )
                    total_elapsed += delay
                    await asyncio.sleep(delay)
                else:
                    raise
        raise RuntimeError("Max retries exceeded for API rate limit")

    async def _run_with_tools(
        self,
        chat_session,
        initial_payload,
        active_provider,
        status=None,
        task_id=None,
        max_iterations=15,
        worker_id=None,
    ):
        import inspect

        o = self._o

        print("\n📡 [NETWORK] Dispatching payload to LLM... (Awaiting response)")
        t0 = time.time()

        response = await self._send_message_with_backoff(chat_session, initial_payload, active_provider)

        # Initial budget check
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            token_count = getattr(response.usage_metadata, "total_token_count", 0)
            o.budget_manager.add_tokens(token_count if isinstance(token_count, int) else 0)
        else:
            heuristic_tokens = (len(str(initial_payload)) // 4) + (
                len(str(getattr(response, "text", ""))) // 4
            )
            o.budget_manager.add_tokens(heuristic_tokens)

        print(f"⏱️ [NETWORK] LLM responded in {time.time() - t0:.1f}s")
        degraded_consecutive = 0  # Track consecutive degraded tool calls

        # [CONTEXT MANAGEMENT CONFIG]
        MAX_HISTORY_TURNS = 6  # Aggressive prune
        MAX_TOOL_OUTPUT_CHARS = 8000  # Hard cap
        MAX_TOOL_ITERATIONS = max_iterations

        iteration_count = 0

        while True:
            tool_calls = active_provider.parse_tool_calls(response)
            if not tool_calls:
                break

            iteration_count += 1
            if iteration_count > MAX_TOOL_ITERATIONS:
                if status:
                    print(
                        f"Task {task_id} aborted: Max tool iterations exceeded.",
                        file=sys.stderr,
                    )
                raise RuntimeError(
                    f"Task {task_id} exceeded max tool iterations ({MAX_TOOL_ITERATIONS}). "
                    "Aborting to prevent infinite loop."
                )

            parts = []
            for call in tool_calls:
                call_id = call.get("id")
                tool_name = call["name"]
                tool_func = None
                for t in o.gemini_tools:
                    if getattr(t, "__name__", "") == tool_name:
                        tool_func = t
                        break

                if tool_func:
                    try:
                        args = call["args"]
                        msg = f"Executing tool: {tool_name} with args: {args}"
                        if status:
                            status.update(f"[bold yellow]{msg}...")
                        print(msg)

                        if tool_name in ["write_file_with_review", "execute_bash"] and task_id is not None:
                            args["task_id"] = task_id
                            # Inject active sandbox_mode into the tool call dynamically
                            args["sandbox_mode"] = getattr(o, "sandbox_mode", "yani-base")
                        if tool_name == "execute_bash" and worker_id is not None:
                            args["worker_id"] = worker_id
                        if inspect.iscoroutinefunction(tool_func):
                            result = await tool_func(**args)
                        else:
                            result = tool_func(**args)

                        # [THE BLEED VALVE: Tool Output Truncation]
                        result_str = str(result)
                        if len(result_str) > MAX_TOOL_OUTPUT_CHARS:
                            if status:
                                status.update(f"[bold red]Truncated massive output from {tool_name}...")
                            result_str = (
                                result_str[:MAX_TOOL_OUTPUT_CHARS]
                                + f"\n\n... [SYSTEM OVERRIDE: Output truncated at {MAX_TOOL_OUTPUT_CHARS} chars "
                                "to prevent token exhaustion. You MUST use tools like `grep`, `head/tail`, "
                                "or `codegraph_search` for targeted extraction.]"
                            )

                        # Track consecutive degraded tool responses
                        if isinstance(result_str, str) and "Degraded] Tool not available" in result_str:
                            degraded_consecutive += 1
                            if degraded_consecutive >= 3:
                                parts.append(
                                    active_provider.format_tool_error(
                                        tool_name,
                                        f"STOP: {tool_name} is degraded. All codegraph tools are unavailable "
                                        "this session. Use read_file and execute_bash only.",
                                        call_id,
                                    )
                                )
                                continue
                        else:
                            degraded_consecutive = 0

                        parts.append(
                            active_provider.format_tool_response(tool_name, result_str, call_id)
                        )
                    except Exception as e:
                        msg = f"Tool {tool_name} failed: {e}"
                        print(f"⚠️ [TOOL ERROR] {msg}")
                        if not status:
                            print(msg)
                        safe_e = str(e)
                        safe_e = re.sub(
                            r"(api_key|password|secret|token)=[\w\d\-]+",
                            r"\1=[REDACTED]",
                            safe_e,
                            flags=re.IGNORECASE,
                        )
                        safe_e = re.sub(r"(sk-[a-zA-Z0-9]{32,})", "[REDACTED]", safe_e)
                        parts.append(
                            active_provider.format_tool_error(tool_name, safe_e, call_id)
                        )
                else:
                    msg = f"Tool {tool_name} not found"
                    if not status:
                        print(msg)
                    parts.append(
                        active_provider.format_tool_error(tool_name, "Tool not found", call_id)
                    )

            if status:
                status.update("[bold cyan]Agent analyzing tool results...")

            print(f"\n📡 [NETWORK] Returning {len(parts)} tool result(s) to LLM... (Awaiting response)")
            t1 = time.time()

            response = await self._send_message_with_backoff(chat_session, parts, active_provider)

            print(f"⏱️ [NETWORK] LLM responded in {time.time() - t1:.1f}s")

            # [THE SLIDING WINDOW: History Pruning]
            chat_session, pruned = await active_provider.prune_history(chat_session, MAX_HISTORY_TURNS)
            if status:
                if pruned:
                    status.update("[bold magenta]Context optimization: Pruned stale chat history...")
                else:
                    status.update(
                        "[bold yellow]Context optimization: Skipped pruning (no safe boundary found or under max)..."
                    )

            # Mid-loop budget check to prevent unbounded token consumption
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                token_count = getattr(response.usage_metadata, "total_token_count", 0)
                o.budget_manager.add_tokens(token_count if isinstance(token_count, int) else 0)
            else:
                heuristic_tokens = (len(str(parts)) // 4) + (
                    len(str(getattr(response, "text", ""))) // 4
                )
                o.budget_manager.add_tokens(heuristic_tokens)
            try:
                o.budget_manager.check_and_harvest()
            except Exception:
                print("Budget threshold reached during tool loop. Stopping execution.", file=sys.stderr)
                raise

        return response
