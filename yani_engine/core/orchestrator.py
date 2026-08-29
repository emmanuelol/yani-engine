import sys
import os
import inspect
import asyncio
import hashlib
from dotenv import load_dotenv
import argparse
import subprocess
import shlex
import re
from contextlib import AsyncExitStack
import shutil
import difflib


from yani_engine.core.locks import _MEMORY_MUTEX, _REGISTRY_LOCK, get_registry_lock
from yani_engine.core.sandbox import execute_bash, _ensure_warm_sandbox, _teardown_warm_sandbox, run_rtk
from yani_engine.core.state import (
    append_handoff_summary, append_session_log_row,
    get_registry_lock, ASTMemoryMapper, 
    update_task_registry_row, CheckpointManager, OrphanRecoveryScanner, 
    TaskRegistryState, read_file, write_file_with_review,
    read_code_block, record_knowledge, register_task_batch,
    flush_task_registry
)
from yani_engine.core.planner import WavePlanner
from yani_engine.core.llm_provider import AbstractLLMProvider

from yani_engine.core.config import config
from yani_engine.core.archiver import archive_stale_sessions


class PlanValidator:
    pass

class BudgetExhaustedException(Exception):
    pass

class DependencyGraphError(Exception):
    pass

class BudgetManager:
    def __init__(self, config_text: str):
        self.estimated_tokens = 0
        self.budget_limit = 5000000
        self.threshold_pct = 80
        
        for line in config_text.splitlines():
            line = line.strip()
            if line.startswith("- budget_limit:"):
                try: self.budget_limit = int(line.split(":")[1].strip())
                except ValueError: pass
            elif line.startswith("- budget_threshold_pct:"):
                try: self.threshold_pct = int(line.split(":")[1].strip())
                except ValueError: pass
                
        self.shutdown_threshold = int(self.budget_limit * (self.threshold_pct / 100.0))
                    
    def add_tokens(self, count: int):
        self.estimated_tokens += count if isinstance(count, int) else 0
        
    def check_and_harvest(self):
        if self.estimated_tokens >= self.shutdown_threshold:
            raise BudgetExhaustedException(f"Budget exhausted: {self.estimated_tokens} >= {self.shutdown_threshold}")

class LLMOrchestrator:
    def __init__(self, **kwargs):
        # FIX: Add an extra ".." to correctly resolve the repository root
        self.plugin_root = kwargs.get("plugin_dir", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
        self.exit_stack = AsyncExitStack()
        self.mcp_sessions = {}
        self.mcp_locks = {}
        self._shutdown_lock = asyncio.Lock()
        self._sys_inst_cache = {} # NEW: Instance-level cache for static instructions
        
        # Inject providers securely from the app config
        self.providers = config.providers
        
        # Determine the primary provider for backwards compatibility in tools
        self.provider = self.providers.get("cloud", list(self.providers.values())[0])

        self.local_tools = [read_file, read_code_block, write_file_with_review, execute_bash, update_task_registry_row, run_rtk, register_task_batch, record_knowledge]
        self.gemini_tools = list(self.local_tools)
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                self.budget_manager = BudgetManager(f.read())
        except Exception:
            self.budget_manager = BudgetManager("")
            
        if config.budget_limit is not None:
            self.budget_manager.budget_limit = config.budget_limit
            self.budget_manager.shutdown_threshold = int(self.budget_manager.budget_limit * (self.budget_manager.threshold_pct / 100.0))
        if config.budget_threshold_pct is not None:
            self.budget_manager.threshold_pct = config.budget_threshold_pct
            self.budget_manager.shutdown_threshold = int(self.budget_manager.budget_limit * (self.budget_manager.threshold_pct / 100.0))
            
        if "budget_limit" in kwargs:
            self.budget_manager.budget_limit = kwargs["budget_limit"]
            self.budget_manager.shutdown_threshold = int(self.budget_manager.budget_limit * (self.budget_manager.threshold_pct / 100.0))


    # Dynamic tool filtering per command to reduce token consumption
    COMMAND_TOOL_WHITELIST = {
        # ADDED: execute_bash and wildcard codegraph_* so the LLM can actually discover the repo
        "start":   {"read_file", "register_task_batch", "write_file_with_review", "execute_bash", "codegraph_*", "context7_*"},
        # STRICT iterate WHITELIST: Blocked add_task to force register_task_batch
        "iterate": {"register_task_batch", "read_file", "read_code_block", "update_task_registry_row", "codegraph_search", "codegraph_impact", "context7_*"},
        # --- NEW EXPLICIT WHITELIST FOR EXECUTE ---
        "execute": {"read_file", "read_code_block", "write_file_with_review", "execute_bash", "update_task_registry_row", "codegraph_*", "context7_*"},
        # ------------------------------------------
        "status":  {"read_file", "execute_bash"},
        "rollback": {"read_file", "execute_bash"},
        "report":  {"read_file", "execute_bash", "update_task_registry_row"},
        "audit":   {"read_file", "read_code_block", "execute_bash", "register_task_batch", "update_task_registry_row", "codegraph_*", "context7_*"},
        "resume":  {"read_file", "execute_bash"},
        "update-docs": {"read_file", "execute_bash", "codegraph_*", "context7_*"}
    }

    def _get_tools_for_command(self, command: str):
        allowed = self.COMMAND_TOOL_WHITELIST.get(command)
        if not allowed:
            filtered = self.gemini_tools
        else:
            filtered = []
            for t in self.gemini_tools:
                t_name = getattr(t, "__name__", "")
                if t_name in allowed or any(t_name.startswith(a.replace("*", "")) for a in allowed if a.endswith("*")):
                    filtered.append(t)
                    
        # GLOBAL SAFETY NET: Physically strip codegraph tools from the schema if the MCP server is offline.
        is_cg_active = getattr(self, "is_codegraph_active", False)
        if not is_cg_active:
            filtered = [t for t in filtered if not getattr(t, "__name__", "").startswith("codegraph_")]
            
        return filtered


    def _create_mcp_wrapper(self, server_name: str, tool):
        async def mcp_wrapper(**kwargs):
            sem = self.mcp_locks.setdefault(server_name, asyncio.Semaphore(getattr(config, "max_parallel_tasks", 3) or 3))
            async with sem:
                session = self.mcp_sessions[server_name]
                try:
                    # FIX: Force a 45-second timeout on all MCP queries to prevent AST deadlocks
                    result = await asyncio.wait_for(session.call_tool(tool.name, arguments=kwargs), timeout=45.0)
                    return "\n".join([x.text for x in result.content if hasattr(x, 'text')])
                except asyncio.TimeoutError:
                    return f"Error: Tool '{tool.name}' timed out after 45 seconds. The query was too broad or the server hung. Narrow your target symbol."
        
        # 1. Strip slashes and hyphens for Gemini compatibility
        safe_name = tool.name.replace("-", "_").replace("/", "_")
        final_name = safe_name if safe_name.startswith(server_name) else f"{server_name}_{safe_name}"
        
        # 2. Hard-bind both name attributes so the SDK caching doesn't overwrite it
        mcp_wrapper.__name__ = final_name
        mcp_wrapper.__qualname__ = final_name
        
        # --- DYNAMIC SIGNATURE INJECTION ---
        params = []
        annotations = {} # 3. Initialize explicit Pydantic annotations dict
        
        if hasattr(tool, 'inputSchema') and tool.inputSchema and "properties" in tool.inputSchema:
            for prop_name, prop_schema in tool.inputSchema["properties"].items():
                ptype = str
                if prop_schema.get("type") == "integer": ptype = int
                elif prop_schema.get("type") == "boolean": ptype = bool
                elif prop_schema.get("type") == "number": ptype = float
                elif prop_schema.get("type") == "array": ptype = list
                
                is_req = prop_name in tool.inputSchema.get("required", [])
                default = inspect.Parameter.empty if is_req else None
                
                # 4. Map the type to the annotations dictionary
                annotations[prop_name] = ptype
                
                params.append(inspect.Parameter(
                    name=prop_name, 
                    kind=inspect.Parameter.KEYWORD_ONLY, 
                    annotation=ptype, 
                    default=default
                ))
        
        mcp_wrapper.__signature__ = inspect.Signature(parameters=params)
        mcp_wrapper.__annotations__ = annotations # 5. Inject into the wrapper
        
        # Enterprise-grade safeguard: Limit tool descriptions to prevent token window exhaustion
        doc_str = getattr(tool, 'description', '')
        if doc_str and len(doc_str) > 1024:
            doc_str = doc_str[:1021] + "..."
        mcp_wrapper.__doc__ = doc_str
        
        return mcp_wrapper

    async def connect_mcp(self):
        """Delegates to mcp_manager.connect_mcp() — MCP lifecycle lives there."""
        from yani_engine.core.mcp_manager import connect_mcp as _connect_mcp
        await _connect_mcp(self)

    async def _graceful_shutdown(self, task_id: str = None):
        if not hasattr(self, "_shutdown_lock"):
            self._shutdown_lock = asyncio.Lock()
        async with self._shutdown_lock:
            if getattr(self, "_is_shutting_down", False):
                return
            self._is_shutting_down = True
            print("CRITICAL: Budget Exhausted. Initiating Graceful Shutdown Sequence...")
            
            # 1. Update task statuses safely via the state manager
            state = TaskRegistryState()
            tasks = await state.get_tasks()
            interrupted_ids = []
            for tid, t in tasks.items():
                if t['status'].strip() == 'in_progress':
                    await update_task_registry_row(tid, 'interrupted')
                    interrupted_ids.append(tid)
            await flush_task_registry()

            # 2. Build the summary string
            summary = f"## Session Handoff Summary\n- Outcome: interrupted-budget\n"
            if task_id:
                summary += f"- Interrupted Task: {task_id}\n"
            elif interrupted_ids:
                summary += f"- Interrupted Tasks: {', '.join(interrupted_ids)}\n"
            summary += "- Recommended Next Scope: Resume interrupted tasks\n"
            
            # 3. Dispatch to the async-safe state writer
            await append_handoff_summary(summary)
            
            await _teardown_warm_sandbox()
            print("Graceful Shutdown Sequence Complete. State preserved in memory.md.")

    async def _get_sliced_memory(self, sections: list) -> str:
        """Extracts only specified sections from memory.md to minimize token consumption."""
        content = await self.local_tools[0]("memory.md")
        if not content or content.startswith("Error"):
            return "Memory state unavailable."
            
        sliced = []
        capture = False
        target_level = 0
        
        for line in content.splitlines():
            stripped = line.strip()
            
            # Check if this line starts any of our target sections (## or ###)
            if any(stripped.startswith(f"## {s}") or stripped.startswith(f"### {s}") for s in sections):
                capture = True
                # Determine the heading level we just matched (2 for ##, 3 for ###)
                target_level = len(stripped) - len(stripped.lstrip("#"))
                
            # Stop capturing if we hit a new heading of the SAME or HIGHER hierarchical level
            elif capture and stripped.startswith("#"):
                current_level = len(stripped) - len(stripped.lstrip("#"))
                if current_level <= target_level:
                    capture = False
                    
            if capture:
                sliced.append(line)
                
        return "\n".join(sliced) if sliced else content

    async def _get_system_instructions(self, command: str = None, task_id: str = None):
        # HYBRID OPTIMIZATION: Strict slicing for execute
        if command == "execute" and task_id:
            memory_content = await self._get_sliced_memory(["Config", "Task Registry", task_id])
        elif command == "iterate":
            # REMOVED "Task Details" to prevent unbounded token bleed. 
            # The LLM must rely on the Task Registry summary or use read_file for specifics.
            memory_content = await self._get_sliced_memory(["Project Goal", "Scope", "Edge Case Coverage", "Task Registry"])
        else:
            memory_content = await self.local_tools[0]("memory.md") or "No memory.md found. Start a new project."

        import hashlib
        mem_hash = hashlib.md5(memory_content.encode('utf-8')).hexdigest()
        cache_key = f"{command}_{task_id}_{mem_hash}"
        if cache_key in self._sys_inst_cache:
            return self._sys_inst_cache[cache_key]

        instructions = [
            "# MISSION",
            "You are yani-engine, an Agent Engineering Harness. Your goal is to systematically analyze, improve, and validate agent projects.",
            await self.local_tools[0](os.path.join(self.plugin_root, "SYSTEM_INSTRUCTIONS.md")) or "Core rules not found.",
        ]

        # Only inject heavy protocols for planning/iterating commands
        if command in (None, "iterate", "start", "audit"):
            instructions.extend([
                await self.local_tools[0](os.path.join(self.plugin_root, "lib", "common-preamble.md")) or "",
                await self.local_tools[0](os.path.join(self.plugin_root, "lib", "compression-policy.md")) or "",
                "# KNOWLEDGE PROTOCOL",
                await self.local_tools[0](os.path.join(self.plugin_root, "lib", "knowledge-protocol.md")) or "",
                "# MEMORY SCHEMA",
                await self.local_tools[0](os.path.join(self.plugin_root, "lib", "memory-schema.md")) or "",
            ])

        # OP-2 Selective Load: Inject the Knowledge Index as semantic memory
        knowledge_index = await self.local_tools[0]("knowledge/index.md")
        if not knowledge_index or knowledge_index.startswith("Error"):
            knowledge_index = "Knowledge registry not yet initialized. Use the record_knowledge tool to capture insights."

        instructions.append(f"# DURABLE SEMANTIC MEMORY (Knowledge Vault)\n{knowledge_index}")
        instructions.append(f"# CURRENT STATE (Working Memory)\n{memory_content}")

        if command and command != "execute":
            skill_path = os.path.join(self.plugin_root, "skills", command, "INSTRUCTIONS.md")
            skill_content = await self.local_tools[0](skill_path)
            if skill_content and not skill_content.startswith("Error"):
                instructions.append(f"# COMMAND SPECIFIC INSTRUCTIONS ({command})\n{skill_content}")
                
        final_instructions = "\n\n".join(instructions)
        self._sys_inst_cache[cache_key] = final_instructions
        return final_instructions



    async def _send_message_with_backoff(self, chat_session, payload, active_provider):
        import random
        import re
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
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "Quota exceeded" in error_str or "500" in error_str or "INTERNAL" in error_str or "503" in error_str:
                    if attempt == max_retries - 1:
                        raise
                    match = re.search(r"retry in (\d+)s", error_str)
                    if match:
                        delay = int(match.group(1)) + random.uniform(2, 5)
                    else:
                        delay = base_delay * (1.5 ** attempt) + random.uniform(0, 5)
                    if total_elapsed + delay > max_total_wait:
                        raise RuntimeError(f"Rate limit backoff exceeded {max_total_wait}s total wait ({total_elapsed:.0f}s elapsed)")
                    print(f"API Rate Limit/Internal Error hit. Task pausing for {delay:.1f}s before retry {attempt+1}/{max_retries}...")
                    total_elapsed += delay
                    await asyncio.sleep(delay)
                else:
                    raise
        raise RuntimeError("Max retries exceeded for API rate limit")

    async def _run_with_tools(self, chat_session, initial_payload, active_provider, status=None, task_id=None, max_iterations=15, worker_id=None):
        import time
        print("\n📡 [NETWORK] Dispatching payload to LLM... (Awaiting response)")
        t0 = time.time()
        
        response = await self._send_message_with_backoff(chat_session, initial_payload, active_provider)
        
        # Initial budget check
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            token_count = getattr(response.usage_metadata, 'total_token_count', 0)
            self.budget_manager.add_tokens(token_count if isinstance(token_count, int) else 0)
        else:
            heuristic_tokens = (len(str(initial_payload)) // 4) + (len(str(getattr(response, 'text', ''))) // 4)
            self.budget_manager.add_tokens(heuristic_tokens)
        
        print(f"⏱️ [NETWORK] LLM responded in {time.time() - t0:.1f}s")
        degraded_consecutive = 0  # Track consecutive degraded tool calls

        # [CONTEXT MANAGEMENT CONFIG]
        MAX_HISTORY_TURNS = 6  # Aggressive prune
        MAX_TOOL_OUTPUT_CHARS = 8000  # Hard cap
        MAX_TOOL_ITERATIONS = max_iterations  # Decreased to handle deep discovery loops

        iteration_count = 0

        while True:
            tool_calls = active_provider.parse_tool_calls(response)
            if not tool_calls:
                break
                
            iteration_count += 1
            if iteration_count > MAX_TOOL_ITERATIONS:
                if status:
                    print(f"Task {task_id} aborted: Max tool iterations exceeded.", file=sys.stderr)
                raise RuntimeError(f"Task {task_id} exceeded max tool iterations ({MAX_TOOL_ITERATIONS}). Aborting to prevent infinite loop.")

            parts = []
            for call in tool_calls:
                call_id = call.get('id')
                tool_name = call['name']
                tool_func = None
                for t in self.gemini_tools:
                    if getattr(t, "__name__", "") == tool_name:
                        tool_func = t
                        break
                
                if tool_func:
                    try:
                        args = call['args']
                        msg = f"Executing tool: {tool_name} with args: {args}"
                        if status:
                            status.update(f"[bold yellow]{msg}...")
                        print(msg)
                        
                        import inspect
                        if tool_name in ["write_file_with_review", "execute_bash"] and task_id is not None:
                            args["task_id"] = task_id
                            # NEW: Inject the active sandbox_mode into the tool call dynamically
                            args["sandbox_mode"] = getattr(self, "sandbox_mode", "yani-base")
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
                            result_str = result_str[:MAX_TOOL_OUTPUT_CHARS] + f"\n\n... [SYSTEM OVERRIDE: Output truncated at {MAX_TOOL_OUTPUT_CHARS} chars to prevent token exhaustion. You MUST use tools like `grep`, `head/tail`, or `codegraph_search` for targeted extraction.]"

                        # Track consecutive degraded tool responses
                        if isinstance(result_str, str) and "Degraded] Tool not available" in result_str:
                            degraded_consecutive += 1
                            if degraded_consecutive >= 3:
                                parts.append(active_provider.format_tool_error(
                                    tool_name,
                                    f"STOP: {tool_name} is degraded. All codegraph tools are unavailable this session. Use read_file and execute_bash only.",
                                    call_id
                                ))
                                continue
                        else:
                            degraded_consecutive = 0

                        parts.append(active_provider.format_tool_response(
                            tool_name,
                            result_str,
                            call_id
                        ))
                    except Exception as e:
                        msg = f"Tool {tool_name} failed: {e}"
                        print(f"⚠️ [TOOL ERROR] {msg}") # Force print to stdout
                        if not status: print(msg)
                        safe_e = str(e)
                        import re
                        safe_e = re.sub(r'(api_key|password|secret|token)=[\w\d\-]+', r'\1=[REDACTED]', safe_e, flags=re.IGNORECASE)
                        safe_e = re.sub(r'(sk-[a-zA-Z0-9]{32,})', '[REDACTED]', safe_e)
                        parts.append(active_provider.format_tool_error(
                            tool_name,
                            safe_e,
                            call_id
                        ))
                else:
                    msg = f"Tool {tool_name} not found"
                    if not status: print(msg)
                    parts.append(active_provider.format_tool_error(
                        tool_name,
                        "Tool not found",
                        call_id
                    ))
            
            if status:
                status.update("[bold cyan]Agent analyzing tool results...")

            print(f"\n📡 [NETWORK] Returning {len(parts)} tool result(s) to LLM... (Awaiting response)")
            t1 = time.time()
            
            response = await self._send_message_with_backoff(chat_session, parts, active_provider)
            
            print(f"⏱️ [NETWORK] LLM responded in {time.time() - t1:.1f}s")

            # [THE SLIDING WINDOW: History Pruning]
            # [FIX]: Await the newly asynchronous provider method to prevent coroutine deadlocks
            chat_session, pruned = await active_provider.prune_history(chat_session, MAX_HISTORY_TURNS)
            if status:
                if pruned:
                    status.update("[bold magenta]Context optimization: Pruned stale chat history...")
                else:
                    status.update("[bold yellow]Context optimization: Skipped pruning (no safe boundary found or under max)...")

            # Mid-loop budget check to prevent unbounded token consumption
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                token_count = getattr(response.usage_metadata, 'total_token_count', 0)
                self.budget_manager.add_tokens(token_count if isinstance(token_count, int) else 0)
            else:
                heuristic_tokens = (len(str(parts)) // 4) + (len(str(getattr(response, 'text', ''))) // 4)
                self.budget_manager.add_tokens(heuristic_tokens)
            try:
                self.budget_manager.check_and_harvest()
            except BudgetExhaustedException:
                print("Budget threshold reached during tool loop. Stopping execution.", file=sys.stderr)
                raise

        return response

    async def execute_task(self, task_id: str, description: str = "", worker_id: str = None):
        """Backwards-compatibility shim. Delegates to TaskExecutor.

        Preserves the public method contract used by test_refactoring.py,
        executor.py _worker(), and any external call sites. The full
        implementation lives in yani_engine.core.task_executor.TaskExecutor.
        """
        from yani_engine.core.task_executor import TaskExecutor
        return await TaskExecutor(self).execute_task(task_id, description, worker_id)

    async def run(self, command: str, args: list):
        # Restored baseline routing: 'execute' defaults to fast tier.
        # execute_task() will dynamically elevate tasks to heavy tier based on effort.
        # Only force the heavy model if the user didn't explicitly override it via CLI/env
        if command in ["iterate", "audit", "start"] and not getattr(config, "model_overridden", False):
            self.model = config.model_heavy
        elif not getattr(config, "model_overridden", False):
            self.model = config.model_fast
        print(f"yani-engine running command: {command}")
        if command == "resume":
            from yani_engine.commands.resume_handler import handle_resume
            result = await handle_resume(self, args)
            if result != "execute":
                return
            command = "execute"

        
        # Skip MCP initialization for commands that do not need structural code analysis or semantic search
        if command not in ("status", "rollback", "report"):
            await self.connect_mcp()
        try:
            if command == "rollback":
                from yani_engine.commands.handlers import handle_rollback
                await handle_rollback(self, args)
                return

            if command == "execute":
                from yani_engine.core.executor import WaveExecutor
                await WaveExecutor(self).execute_pending_waves(args)

            elif command == "report":
                from yani_engine.commands.handlers import handle_report
                await handle_report(self, args)
                return

            elif command == "audit":
                from yani_engine.commands.audit_handler import handle_audit
                await handle_audit(self, args)
                return

            elif command == "status":
                from yani_engine.commands.handlers import handle_status
                await handle_status(self, args)
                return

            elif command == "update-docs":
                from yani_engine.commands.docs_handler import handle_update_docs
                await handle_update_docs(self, args)
                return

            elif command == "start":
                from yani_engine.commands.llm_handlers import handle_start
                await handle_start(self, args)

            elif command == "iterate":
                from yani_engine.commands.llm_handlers import handle_iterate
                await handle_iterate(self, args)

            else:
                # FIX: Use the decoupled provider interface
                self.chat_session = await self.provider.create_chat_session(
                    model_name=getattr(self, "model", config.model),
                    tools=self._get_tools_for_command(command)
                )

                sys_inst = await self._get_system_instructions(command)
                payload = f"{sys_inst}\n\nUSER DIRECTIVE: Execute the `{command}` command with arguments {args}. Follow your COMMAND SPECIFIC INSTRUCTIONS strictly. Do not ask for user input if a tool can accomplish the task."
                from rich.console import Console
                console = Console()
                with console.status(f"[bold cyan]Running {command} agent...", spinner="dots") as status:
                    try:
                        max_iters = 30 if command in ("start", "iterate") else 15
                        response = await self._run_with_tools(self.chat_session, payload, self.provider, status=status, max_iterations=max_iters)
                    except RuntimeError as e:
                        # FIX: Catch max iterations gracefully to prevent stack trace crash
                        print(f"\n[bold red]Agent execution aborted: {e}[/bold red]")
                        return
                    except BudgetExhaustedException:
                        print(f"\n[bold red]Budget threshold reached during {command}. Attempting token clearance...[/bold red]")
                        rtk_out = await run_rtk("gain")
                        import re
                        match = re.search(r"(\d+)", rtk_out)
                        rtk_savings = int(match.group(1)) if match else 50000
                        self.budget_manager.estimated_tokens = max(0, self.budget_manager.estimated_tokens - rtk_savings)
                        try:
                            response = await self._run_with_tools(self.chat_session, payload, self.provider, status=status)
                        except (BudgetExhaustedException, RuntimeError) as e:
                            print(f"Task failed or budget threshold blocked retry: {e}")
                            await self._graceful_shutdown()
                            return

                # FIX: Use provider parser instead of raw Gemini properties
                unhandled_calls = self.provider.parse_tool_calls(response)
                if unhandled_calls:
                    print("Function Calls that were not handled:", unhandled_calls)

                # Safely extract text depending on provider response structure
                final_text = getattr(response, 'text', '') if hasattr(response, 'text') else str(response)
                print(final_text)

        finally:
            await _teardown_warm_sandbox()
            if command not in ["status", "report"]:
                await archive_stale_sessions()
            
            # [FIX]: Drain and close all async HTTP client sessions to prevent OS-level file descriptor leaks
            if hasattr(self, "providers"):
                for provider in self.providers.values():
                    if hasattr(provider, "aclose"):
                        await provider.aclose()
                        
            await self.exit_stack.aclose()

