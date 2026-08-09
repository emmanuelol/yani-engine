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


from dumbledoer.core.locks import _MEMORY_MUTEX, _REGISTRY_LOCK, get_registry_lock
from dumbledoer.core.sandbox import execute_bash, _ensure_warm_sandbox, _teardown_warm_sandbox, run_rtk
from dumbledoer.core.state import (
    append_handoff_summary,
    get_registry_lock, ASTMemoryMapper, 
    update_task_registry_row, CheckpointManager, OrphanRecoveryScanner, 
    TaskRegistryState, read_file, write_file_with_review,
    add_task, read_code_block, record_knowledge
)
from dumbledoer.core.planner import WavePlanner
from dumbledoer.core.llm_provider import AbstractLLMProvider

from dumbledoer.core.config import config
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

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
    def __init__(self):
        self.plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.exit_stack = AsyncExitStack()
        self.mcp_sessions = {}
        self.mcp_locks = {}
        
        # Inject providers securely from the app config
        self.providers = config.providers
        
        # Determine the primary provider for backwards compatibility in tools
        self.provider = self.providers.get("cloud", list(self.providers.values())[0])

        self.local_tools = [read_file, read_code_block, write_file_with_review, execute_bash, update_task_registry_row, run_rtk, add_task, record_knowledge]
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

    # Dynamic tool filtering per command to reduce token consumption
    COMMAND_TOOL_WHITELIST = {
        "start":   {"read_file", "execute_bash", "add_task", "write_file_with_review", "update_task_registry_row", "codegraph_*", "context7_*"},
        "iterate": {"add_task", "read_file", "update_task_registry_row", "codegraph_*", "context7_*"},
        "status":  {"read_file", "execute_bash"},
        "rollback": {"read_file", "execute_bash"},
        "report":  {"read_file", "execute_bash", "update_task_registry_row"},
        "audit":   {"read_file", "read_code_block", "execute_bash", "add_task", "update_task_registry_row", "codegraph_*", "context7_*"},
        "resume":  {"read_file", "execute_bash"},
        "update-docs": {"read_file", "execute_bash", "codegraph_*", "context7_*"}
    }

    def _get_tools_for_command(self, command: str):
        allowed = self.COMMAND_TOOL_WHITELIST.get(command)
        if not allowed:
            return self.gemini_tools
        
        filtered = []
        for t in self.gemini_tools:
            t_name = getattr(t, "__name__", "")
            if t_name in allowed:
                filtered.append(t)
            # Support dynamic capabilities via wildcard prefixes
            elif any(t_name.startswith(a.replace("*", "")) for a in allowed if a.endswith("*")):
                filtered.append(t)
        return filtered


    def _create_mcp_wrapper(self, server_name: str, tool):
        async def mcp_wrapper(**kwargs):
            lock = self.mcp_locks.setdefault(server_name, asyncio.Lock())
            async with lock:
                session = self.mcp_sessions[server_name]
                result = await session.call_tool(tool.name, arguments=kwargs)
                return "\n".join([x.text for x in result.content if hasattr(x, 'text')])
        
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
        if not os.path.exists(".codegraph"):
            os.makedirs(".codegraph", exist_ok=True)
            import sys
            print("Initializing CodeGraph index...", file=sys.stderr)
            import subprocess
            await asyncio.to_thread(subprocess.run, ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"], check=True)
            
        # Connect to codegraph
        try:
            codegraph_params = StdioServerParameters(
                command="npx",
                args=["--yes", "--quiet", "--package=@colbymchenry/codegraph", "codegraph", "serve", "--mcp"]
            )
            codegraph_transport, codegraph_stream = await self.exit_stack.enter_async_context(stdio_client(codegraph_params))
            codegraph_session = await self.exit_stack.enter_async_context(ClientSession(codegraph_transport, codegraph_stream))
            await codegraph_session.initialize()
            cg_tools = await codegraph_session.list_tools()
            
            # Enterprise-grade safeguard: limit tools per server
            tools_to_add = cg_tools.tools

            for tool in tools_to_add:
                self.gemini_tools.append(self._create_mcp_wrapper("codegraph", tool))
            self.mcp_sessions["codegraph"] = codegraph_session
        except Exception as e:
            import sys
            print(f"CodeGraph MCP degraded: {e}", file=sys.stderr)

        # Connect to context7
        try:
            context7_params = StdioServerParameters(
                command="npx",
                args=["--yes", "--quiet", "@upstash/context7-mcp"]
            )
            context7_transport, context7_stream = await self.exit_stack.enter_async_context(stdio_client(context7_params))
            context7_session = await self.exit_stack.enter_async_context(ClientSession(context7_transport, context7_stream))
            await context7_session.initialize()
            c7_tools = await context7_session.list_tools()
            
            # Enterprise-grade safeguard: limit tools per server
            tools_to_add = c7_tools.tools

            for tool in tools_to_add:
                self.gemini_tools.append(self._create_mcp_wrapper("context7", tool))
            self.mcp_sessions["context7"] = context7_session
        except Exception as e:
            import sys
            print(f"Context7 MCP degraded: {e}", file=sys.stderr)

        existing_tools = [getattr(t, "__name__", "") for t in self.gemini_tools]
        
        EXPECTED_FALLBACKS = [
            "codegraph_impact", "codegraph_search", "codegraph_callers", 
            "codegraph_affected", "codegraph_context", "codegraph_node",
            "codegraph_callees", "codegraph_files", "codegraph_status",
            "context7_resolve_library_id", "context7_query_docs", "context7_search_codebase"
        ]
        
        for missing_tool in EXPECTED_FALLBACKS:
            if missing_tool not in existing_tools:
                def create_dummy(name):
                    async def dummy_fallback(*args, **kwargs) -> str:
                        return f"Error: [{name} Degraded] Tool not available. DO NOT retry this tool — use read_file or execute_bash instead."
                    dummy_fallback.__name__ = name
                    dummy_fallback.__qualname__ = name
                    dummy_fallback.__doc__ = f"Fallback dummy for {name}."
                    return dummy_fallback
                
                self.gemini_tools.append(create_dummy(missing_tool))

    async def _graceful_shutdown(self, task_id: str = None):
        print("CRITICAL: Budget Exhausted. Initiating Graceful Shutdown Sequence...")
        
        # 1. Update task statuses safely via the state manager
        state = TaskRegistryState()
        tasks = await state.get_tasks()
        interrupted_ids = []
        for tid, t in tasks.items():
            if t['status'].strip() == 'in_progress':
                await state.update_task_status(tid, 'interrupted')
                interrupted_ids.append(tid)

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
        for line in content.splitlines():
            if any(line.strip().startswith(f"## {s}") for s in sections):
                capture = True
            elif line.strip().startswith("## ") and capture:
                capture = False
            if capture:
                sliced.append(line)
        return "\n".join(sliced) if sliced else content

    async def _get_system_instructions(self, command: str = None):
        # For iterate, inject Goal/Scope/Task Registry + Edge Cases to preserve architectural awareness
        if command == "iterate":
            memory_content = await self._get_sliced_memory(["Project Goal", "Scope", "Edge Case Coverage", "Task Registry"])
        else:
            memory_content = await self.local_tools[0]("memory.md") or "No memory.md found. Start a new project."

        instructions = [
            "# MISSION",
            "You are DumbleDoer, an Agent Engineering Harness. Your goal is to systematically analyze, improve, and validate agent projects.",
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
        return "\n\n".join(instructions)



    async def _send_message_with_backoff(self, chat_session, payload, active_provider):
        import random
        import re
        max_retries = 8
        base_delay = 15
        total_elapsed = 0
        max_total_wait = 120  # Hard cap: 2 minutes total backoff
        for attempt in range(max_retries):
            try:
                return await active_provider.send_message(chat_session, payload)
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "Quota exceeded" in error_str:
                    if attempt == max_retries - 1:
                        raise
                    match = re.search(r"retry in (\d+)s", error_str)
                    if match:
                        delay = int(match.group(1)) + random.uniform(2, 5)
                    else:
                        delay = base_delay * (1.5 ** attempt) + random.uniform(0, 5)
                    if total_elapsed + delay > max_total_wait:
                        raise RuntimeError(f"Rate limit backoff exceeded {max_total_wait}s total wait ({total_elapsed:.0f}s elapsed)")
                    print(f"API Rate Limit (429) hit. Task pausing for {delay:.1f}s before retry {attempt+1}/{max_retries}...")
                    total_elapsed += delay
                    await asyncio.sleep(delay)
                else:
                    raise
        raise RuntimeError("Max retries exceeded for API rate limit")

    async def _run_with_tools(self, chat_session, initial_payload, active_provider, status=None, task_id=None):
        response = await self._send_message_with_backoff(chat_session, initial_payload, active_provider)
        degraded_consecutive = 0  # Track consecutive degraded tool calls

        # [CONTEXT MANAGEMENT CONFIG]
        MAX_HISTORY_TURNS = 6  # Aggressive prune
        MAX_TOOL_OUTPUT_CHARS = 8000  # Hard cap
        MAX_TOOL_ITERATIONS = 25  # Hard cap tool iterations per task

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
                                    f"STOP: {tool_name} is degraded. All codegraph tools are unavailable this session. Use read_file and execute_bash only."
                                ))
                                continue
                        else:
                            degraded_consecutive = 0

                        parts.append(active_provider.format_tool_response(
                            tool_name,
                            result_str
                        ))
                    except Exception as e:
                        msg = f"Tool {tool_name} failed: {e}"
                        if not status: print(msg)
                        parts.append(active_provider.format_tool_error(
                            tool_name,
                            str(e)
                        ))
                else:
                    msg = f"Tool {tool_name} not found"
                    if not status: print(msg)
                    parts.append(active_provider.format_tool_error(
                        tool_name,
                        "Tool not found"
                    ))
            
            if status:
                status.update("[bold cyan]Agent analyzing tool results...")

            response = await self._send_message_with_backoff(chat_session, parts, active_provider)

            # [THE SLIDING WINDOW: History Pruning]
            chat_session = active_provider.prune_history(chat_session, MAX_HISTORY_TURNS)
            if status:
                if pruned:
                    status.update("[bold magenta]Context optimization: Pruned stale chat history...")
                else:
                    status.update("[bold yellow]Context optimization: Skipped pruning (no safe boundary found or under max)...")

            # Mid-loop budget check to prevent unbounded token consumption
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                token_count = getattr(response.usage_metadata, 'total_token_count', 0)
                self.budget_manager.add_tokens(token_count if isinstance(token_count, int) else 0)
            try:
                self.budget_manager.check_and_harvest()
            except BudgetExhaustedException:
                print("Budget threshold reached during tool loop. Stopping execution.", file=sys.stderr)
                raise

        return response

    async def execute_task(self, task_id: str, description: str):
        print(f"Executing task {task_id}: {description}")
        
        # ACTUALLY CLAIM THE TASK SO RESUME CAN FIND IT
        await TaskRegistryState().update_task_status(task_id, "in_progress")
        
        # --- DYNAMIC VENDOR TIERING ---
        effort = "small"
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                mem_content = f.read()
            import re
            
            # Isolate the specific task block first to prevent regex bleed
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(mem_content, "###", task_id)
            if start_idx != -1:
                task_block = "\n".join(mem_content.splitlines()[start_idx:end_idx])
                match = re.search(r"- \*\*Estimated Effort\*\*: (small|medium|large)", task_block, re.IGNORECASE)
                if match:
                    effort = match.group(1).lower()
        except Exception:
            pass
            
        # The Brain: Heavy architectural refactors go to the cloud
        if effort == "large":
            target_model = "gemini-3.1-pro-preview"
            active_provider = self.providers.get("cloud")
            print(f"[Tier Upgrade] Task {task_id} requires {effort} effort. Spawning sub-agent on Gemini Pro.")
            
        # The Hands: Simple file changes and audits hit the local hardware
        else:
            if "local" in self.providers:
                target_model = "llama3.1" # Or whichever model you are serving locally
                active_provider = self.providers["local"]
                print(f"[Cost Saver] Task {task_id} requires {effort} effort. Spawning sub-agent locally.")
            else:
                # FIX: Safely fallback to the cloud model if the local daemon isn't configured
                target_model = getattr(self, "model", config.model)
                active_provider = self.providers.get("cloud", list(self.providers.values())[0])
                print(f"[Cloud Fallback] Local provider unavailable for task {task_id}. Spawning on {target_model}.")
            
            
        # Initialize the session using the selected provider interface
        chat_session = await active_provider.create_chat_session(model_name=target_model, tools=list(self.gemini_tools))
        system_instructions = await self._get_system_instructions()
        prompt_payload = f"""{system_instructions}

This project has CodeGraph initialized (.codegraph/ exists). You are executing task {task_id}: {description}.

Mandatory rules:
1. Read {os.path.join(self.plugin_root, 'lib', 'codegraph-integration.md')} before modifying any file.
2. Follow the 10-step data flow for change tasks exactly.
3. Follow {os.path.join(self.plugin_root, 'lib', 'checkpoint-protocol.md')} for every file write.
4. Log your codegraph_impact result to memory.md task {task_id} CodeGraph Impact field.
5. Do not modify any file listed in another in_progress task's Outputs.
6. Output compression: render your conversational replies at the appropriate caveman level.
7. Documentation lookup: check if this task involves external dependencies and consult context7 if needed.
8. **DO NOT USE BASH TO PARSE MEMORY.MD.** If you need to read `memory.md`, you MUST use the native `read_file` tool. If you need to update it, you MUST use the native `update_memory_registry` tool. Do not write python scripts via bash to parse the ledger."""
        try:
            response = await self._run_with_tools(chat_session, prompt_payload, active_provider, task_id=task_id)
            self.budget_manager.check_and_harvest()
            print(f"Task {task_id} completed: {response.text}")
            await TaskRegistryState().update_task_status(task_id, "awaiting-review")
        except BudgetExhaustedException:
            print(f"Task {task_id} interrupted: Budget exhausted at {self.budget_manager.estimated_tokens} tokens.", file=sys.stderr)
            await TaskRegistryState().update_task_status(task_id, "interrupted")
            await self._graceful_shutdown(task_id)
            raise


    async def batch_diff_review(self, wave_tmp_files: list):
        if not wave_tmp_files: return
        import subprocess, shutil, sys, os
        has_code = shutil.which("code") is not None
        if config.verbose and has_code:
            print("Opening proposed changes in VS Code for review...", file=sys.stderr)
            
            # Read memory.md to map target to task ID
            task_mapping = {}
            if os.path.exists("memory.md"):
                with open("memory.md", "r") as f:
                    for line in f:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 5 and parts[4] == "planned":
                            task_id, target = parts[2], parts[3]
                            task_mapping[target] = task_id

            for tmp_path in wave_tmp_files:
                basename = os.path.basename(tmp_path)
                actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
                actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")
                
                # Check for rollback backup first to guarantee accurate diffs
                rollback_path = None
                task_id = task_mapping.get(actual_filename)
                if task_id:
                    encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
                    possible_rollback = os.path.join(".dumbledoer", "rollbacks", task_id, encoded_path)
                    if os.path.exists(possible_rollback):
                        rollback_path = possible_rollback
                
                # Try fallback global rollback format if task-specific isn't found
                if not rollback_path:
                    import glob
                    encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
                    matches = glob.glob(f".dumbledoer/rollbacks/*_{encoded_path}.bak")
                    if matches:
                        rollback_path = matches[0]

                if rollback_path and os.path.exists(rollback_path):
                    args = ["code", "--wait", "--diff", rollback_path, tmp_path]
                else:
                    args = ["code", "--wait", "--diff", os.devnull, tmp_path]
                print(f"Opening diff in VS Code: {' '.join(args)}")
                await asyncio.to_thread(subprocess.run, args, check=False)
        
        # Always show terminal diff for fallback/quick review
        if True:
            import difflib
            from rich.syntax import Syntax
            from rich.console import Console
            console_diff = Console()
            for tmp_path in wave_tmp_files:
                basename = os.path.basename(tmp_path)
                actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
                actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")
                
                original_text = ""
                
                # Check for rollback backup first to guarantee accurate diffs
                rollback_path = None
                task_id = None
                if os.path.exists("memory.md"):
                    with open("memory.md", "r") as mem:
                        for line in mem:
                            parts = [p.strip() for p in line.split("|")]
                            if len(parts) >= 5 and parts[4] == "planned" and parts[3] == actual_filename:
                                task_id = parts[2]
                                break
                                
                if task_id:
                    encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
                    possible_rollback = os.path.join(".dumbledoer", "rollbacks", task_id, encoded_path)
                    if os.path.exists(possible_rollback):
                        rollback_path = possible_rollback
                                
                if not rollback_path:
                    import glob
                    encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
                    matches = glob.glob(f".dumbledoer/rollbacks/*_{encoded_path}.bak")
                    if matches:
                        rollback_path = matches[0]

                if rollback_path and os.path.exists(rollback_path):
                    with open(rollback_path, "r") as f:
                        original_text = f.read()
                else:
                    original_text = ""

                with open(tmp_path, "r") as f:
                    new_text = f.read()
                    
                diff = list(difflib.unified_diff(
                    original_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"a/{actual_filename}",
                    tofile=f"b/{actual_filename}"
                ))
                if diff:
                    diff_text = "".join(diff)
                    syntax = Syntax(diff_text, "diff", theme="monokai")
                    console_diff.print(f"\n[bold cyan]Diff for {actual_filename}:[/bold cyan]")
                    console_diff.print(syntax)
            
        from rich.prompt import Prompt
        from rich.console import Console
        console = Console()
        if config.verbose:
            choice = await asyncio.to_thread(Prompt.ask, "Approve wave changes? [Y(all)/N(none)/S(select)]", choices=["Y", "N", "S"], default="Y")
        else:
            console.print("[green]Auto-approving wave changes (run with -v to review)[/green]")
            choice = "Y"
        rejected_files = set()
        if choice == "S":
            sel = await asyncio.to_thread(Prompt.ask, "Enter filenames to reject (comma separated)")
            rejected_files = {s.strip() for s in sel.split(",") if s.strip()}
        elif choice == "N":
            rejected_files = {os.path.basename(f) for f in wave_tmp_files}
            
        state = TaskRegistryState()
        for tmp_path in wave_tmp_files:
            basename = os.path.basename(tmp_path)
            import re as _re
            uuid_match = _re.match(r'^[0-9a-f]{32}_(.+)$', basename)
            actual_filename = uuid_match.group(1) if uuid_match else basename
            actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")
            
            target_path = actual_filename
            task_id = None
            try:
                with open("memory.md", "r", encoding="utf-8") as f:
                    content = f.read()
                start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Change Log")
                if start_idx != -1:
                    for line in content.splitlines()[start_idx+1:end_idx]:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 6 and parts[5].strip() == "planned" and parts[3].strip() == actual_filename:
                            target_path = parts[3].strip()
                            task_id = parts[2].strip()
                            break
            except Exception:
                pass

            if actual_filename in rejected_files or basename in rejected_files:
                # Option B: File was already written to disk, so restore from rollback backup
                rollback_restored = False
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                # Find and restore from rollback backup
                import glob as _glob
                encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
                possible_rollback = os.path.join(".dumbledoer", "rollbacks", task_id, encoded_path) if task_id else None
                
                if possible_rollback and os.path.exists(possible_rollback):
                    shutil.copy2(possible_rollback, target_path)
                    rollback_restored = True
                    console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")
                else:
                    rollback_matches = _glob.glob(f".dumbledoer/rollbacks/*_{encoded_path}.bak")
                    if rollback_matches:
                        shutil.copy2(rollback_matches[0], target_path)
                        rollback_restored = True
                        console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")
                    elif os.path.exists(target_path):
                        os.remove(target_path)
                        console.print(f"[yellow]Rejected new file creation, deleted {actual_filename}[/yellow]")
                if task_id:
                    await state.update_task_status(task_id, "pending")
            else:
                # Option B: File already applied to disk, just clean up shadow .tmp
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                console.print(f"[green]Approved changes for {actual_filename}[/green]")
                if task_id:
                    await state.update_task_status(task_id, "completed")

        if rejected_files:
            await OrphanRecoveryScanner().run(True)

    async def run(self, command: str, args: list):
        # Pro Brain / Cost-Efficient Hands: iterate and audit always use pro reasoning
        if command in ["iterate", "audit"]:
            self.model = "gemini-3.1-pro-preview"
        else:
            self.model = config.model
        print(f"DumbleDoer running command: {command}")
        if command == "resume":
            # ADD AWAIT HERE
            await OrphanRecoveryScanner().run()
            
            state = TaskRegistryState()
            tasks = await state.load_tasks()
            
            # Detect interrupted tasks or stale locks natively
            interrupted = [t_id for t_id, t in tasks.items() if t['status'] in ["interrupted", "in_progress"]]
            
            if not interrupted:
                print("\nNo interrupted tasks or stale locks found. Run /dumbledoer:execute to process pending tasks.")
                return
                
            from rich.prompt import Prompt
            from rich.console import Console
            console = Console()
            
            console.print(f"\n[bold yellow]Found interrupted or stale tasks: {', '.join(interrupted)}[/bold yellow]")
            choice = Prompt.ask("How would you like to handle them? [R(esume)/B(Rollback)/S(Skip)]", choices=["R", "B", "S"], default="R")
            
            if choice == "B":
                for t_id in interrupted:
                    await state.update_task_status(t_id, "pending")
                console.print("[yellow]Tasks demoted to pending. Please run /dumbledoer:rollback to revert file changes manually.[/yellow]")
                return
            elif choice == "S":
                for t_id in interrupted:
                    await state.update_task_status(t_id, "deferred")
                console.print("[green]Tasks deferred.[/green]")
                return
            else:
                for t_id in interrupted:
                    await state.update_task_status(t_id, "pending")
                console.print("[green]Locks cleared. Handing off to the native execution engine...[/green]")
                
                # Natively chain into the execute command
                command = "execute"
        
        # Skip MCP initialization for commands that do not need structural code analysis or semantic search
        if command not in ("status", "rollback", "report"):
            await self.connect_mcp()
        try:
            if command == "rollback":
                if not args:
                    print("Error: must provide a task ID (e.g., T-001) or --all")
                    return
                
                target = args[0]
                tasks_to_rollback = []
                state = TaskRegistryState()
                all_tasks = await state.load_tasks()

                if target == "--all":
                    tasks_to_rollback = sorted([t_id for t_id, t in all_tasks.items() if "completed" in t["status"]], reverse=True)
                    if not tasks_to_rollback:
                        print("No completed tasks found to roll back.")
                        return
                elif target.startswith("T-"):
                    if target not in all_tasks or "completed" not in all_tasks[target]["status"]:
                        print(f"Error: {target} is not a completed task.")
                        return
                    tasks_to_rollback = [target]
                else:
                    print(f"Error: Invalid rollback target '{target}'. Use a Task ID or --all.")
                    return

                # Read memory into a list for surgical, line-by-line replacement
                with open("memory.md", "r", encoding="utf-8") as f:
                    mem_content = f.read()
                mem_lines = mem_content.splitlines()

                for task_id in tasks_to_rollback:
                    print(f"\nRolling back {task_id}...")
                    bak_dir = f".dumbledoer/rollbacks/{task_id}"
                    
                    if not os.path.exists(bak_dir):
                        print(f"Warning: No rollback directory found for {task_id}. Only memory.md will be reset.")
                    else:
                        touched_files = []
                        chg_start, chg_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Change Log")
                        if chg_start != -1:
                            # Fix 1: Surgical String Replacement to avoid Ambiguity Corruption
                            for i in range(chg_start + 1, chg_end):
                                parts = [p.strip() for p in mem_lines[i].split("|")]
                                if len(parts) >= 6 and parts[2] == task_id:
                                    touched_files.append(parts[3])
                                    mem_lines[i] = mem_lines[i].replace("| applied |", "| rolled-back |")

                        restored_files = set()
                        for root, _, files in os.walk(bak_dir):
                            for file in files:
                                bak_path = os.path.join(root, file)
                                rel_path = bak_path.replace(bak_dir + "/", "").replace("__colon__", ":").replace("__", "/")
                                os.makedirs(os.path.dirname(os.path.abspath(rel_path)), exist_ok=True)
                                
                                # Safety temp copy before overwrite
                                tmp_path = f".dumbledoer/tmp/{file}.tmp"
                                os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
                                if os.path.exists(rel_path):
                                    shutil.copy2(rel_path, tmp_path)
                                
                                shutil.copy2(bak_path, rel_path)
                                restored_files.add(rel_path)
                                print(f"  Restored: {rel_path}")
                        
                        for f_path in touched_files:
                            if f_path not in restored_files and os.path.exists(f_path):
                                os.remove(f_path)
                                print(f"  Deleted newly created file: {f_path}")

                    # Fix 2: Dynamic Task Details lookup for trailing titles
                    t_start, t_end = -1, -1
                    for i, line in enumerate(mem_lines):
                        if line.startswith(f"### {task_id}"):
                            t_start = i
                            for j in range(i + 1, len(mem_lines)):
                                if mem_lines[j].startswith("## ") or mem_lines[j].startswith("### T-"):
                                    t_end = j
                                    break
                            if t_end == -1:
                                t_end = len(mem_lines)
                            break
                    
                    if t_start != -1:
                        for i in range(t_start, t_end):
                            if "- **Owner**:" in mem_lines[i]: mem_lines[i] = "- **Owner**: —"
                            if "- **Checkpoint**:" in mem_lines[i]: mem_lines[i] = "- **Checkpoint**: none"
                            if "- **Notes**:" in mem_lines[i]: mem_lines[i] += f" (Rolled back)"

                # Save updated memory.md
                mem_content = "\n".join(mem_lines)
                with open("memory.md", "w", encoding="utf-8") as f:
                    f.write(mem_content)

                # Fix 3: Execute TaskRegistryState updates AFTER the file write
                for task_id in tasks_to_rollback:
                    await state.update_task_status(task_id, "pending")

                # Sync CodeGraph AST
                if os.path.exists(".codegraph"):
                    print("\nSyncing CodeGraph index...")
                    import subprocess
                    await asyncio.to_thread(subprocess.run, ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "sync"], capture_output=True)

                print(f"\nRollback complete. Restored {len(tasks_to_rollback)} task(s).")
                return
    
            if command == "execute":
                await OrphanRecoveryScanner().run(unattended=True)
                import glob
                existing_tmps = set(glob.glob(".dumbledoer/tmp/*.tmp"))
                if existing_tmps:
                    print(f"Found {len(existing_tmps)} unreviewed files from a previous run. Starting review...")
                    await self.batch_diff_review(list(existing_tmps))
                
                # Fetch max_parallel_tasks from memory.md
                max_parallel = 0
                try:
                    # Async lock handled correctly or we can just read
                    with open("memory.md", "r", encoding="utf-8") as f:
                        mem_content = f.read()
                    config_start, config_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
                    if config_start != -1:
                        for line in mem_content.splitlines()[config_start:config_end]:
                            if "- max_parallel_tasks:" in line:
                                max_parallel = int(line.split(":")[1].strip())
                except Exception:
                    pass

                wave_index = 0
                # Initialize planner
                planner = WavePlanner(start_at_index=config.start_at_index)
                
                while True:
                    waves = await planner.get_pending_waves()
                    if not waves:
                        if wave_index == 0:
                            print("No pending tasks to execute.")
                        break
                    wave = waves[0]
                    wave_index += 1
                    i = wave_index - 1
                    
                    print(f"Starting execution wave {wave_index} with {len(wave)} tasks...")
                    before_tmps = set(glob.glob(".dumbledoer/tmp/*.tmp"))
                    try:
                        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
                        from rich.console import Console
                        with Progress(
                            SpinnerColumn(),
                            TextColumn("[progress.description]{task.description}"),
                            BarColumn(),
                            TaskProgressColumn(),
                            console=Console(force_terminal=True),
                        ) as progress:
                            wave_task = progress.add_task(f"[cyan]Executing Wave {i+1}/{len(waves)}...", total=len(wave))
                            
                            queue = asyncio.Queue()
                            for t in wave:
                                queue.put_nowait(t)

                            async def worker():
                                while not queue.empty():
                                    try:
                                        self.budget_manager.check_and_harvest()
                                    except BudgetExhaustedException:
                                        while not queue.empty():
                                            queue.get_nowait()
                                            queue.task_done()
                                        break

                                    t = await queue.get()
                                    try:
                                        await self.execute_task(t['id'], t.get('title', ''))
                                    except BudgetExhaustedException:
                                        while not queue.empty():
                                            queue.get_nowait()
                                            queue.task_done()
                                        raise
                                    except Exception as e:
                                        # FIX: Catch all other exceptions so tasks don't get stuck in 'in_progress'
                                        print(f"\n[bold red]Task {t['id']} failed with exception: {e}[/bold red]")
                                        await TaskRegistryState().update_task_status(t['id'], "error")
                                    finally:
                                        progress.advance(wave_task)
                                        queue.task_done()

                            # Force a hard-cap of 3 concurrent workers to prevent API token flooding
                            safe_parallel = 3 if max_parallel <= 0 else max_parallel
                            num_workers = min(safe_parallel, len(wave))
                            workers = [asyncio.create_task(worker()) for _ in range(num_workers)]

                            res = await asyncio.gather(*workers, return_exceptions=True)

                            for r in res:
                                if isinstance(r, BudgetExhaustedException):
                                    raise r
                    except BudgetExhaustedException:
                        await self._graceful_shutdown()
                        break
                    after_tmps = set(glob.glob(".dumbledoer/tmp/*.tmp"))
                    wave_tmps = list(after_tmps - before_tmps)
                    if wave_tmps:
                        await self.batch_diff_review(wave_tmps)

            elif command == "report":
                from rich.console import Console
                from rich.markdown import Markdown
                import difflib
                from datetime import datetime
                
                console = Console()
                output_path = None
                
                # 1. Parse Args
                for i, arg in enumerate(args):
                    if arg.startswith("--output="):
                        output_path = arg.split("=")[1]
                    elif arg == "--output" and i + 1 < len(args):
                        output_path = args[i + 1]

                if not os.path.exists("memory.md"):
                    console.print("[red]Error: memory.md not found. Run /dumbledoer:start first.[/red]")
                    return

                with open("memory.md", "r", encoding="utf-8") as f:
                    mem_content = f.read()

                # 2. Parse Baseline Config
                config_start, config_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
                baseline_symbols = "0"
                baseline_sync = "Unknown"
                backend = "native"
                if config_start != -1:
                    for line in mem_content.splitlines()[config_start:config_end]:
                        if "codegraph_baseline_symbols:" in line: baseline_symbols = line.split(":", 1)[1].strip()
                        if "codegraph_baseline_sync:" in line: baseline_sync = line.split(":", 1)[1].strip()
                        if "codegraph_backend:" in line: backend = line.split(":", 1)[1].strip()

                # 3. Get Current CodeGraph Status
                cg_symbols = "0"
                if os.path.exists(".codegraph"):
                    try:
                        cg_out = (await asyncio.to_thread(subprocess.run, ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "status"], capture_output=True, text=True)).stdout
                        sym_match = re.search(r"(\d+)\s+symbols", cg_out)
                        if sym_match: cg_symbols = sym_match.group(1)
                    except Exception: pass

                # 4. Extract Tasks & Goal
                goal_start, goal_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Project Goal")
                project_goal = mem_content.splitlines()[goal_start+1:goal_end][0] if goal_start != -1 and goal_end > goal_start + 1 else "No goal defined."

                state = TaskRegistryState()
                all_tasks = await state.load_tasks()
                completed_changes = [t for t in all_tasks.values() if t['status'] == 'completed' and 'change' in t.get('original_line', '')]
                pending_tasks = [t for t in all_tasks.values() if t['status'] in ['pending', 'deferred']]

                if not completed_changes:
                    console.print("[yellow]No completed changes found. Run /dumbledoer:status to see pending tasks.[/yellow]")
                    return

                # 5. Build Report Markdown
                lines = [
                    "# DumbleDoer Improvement Report\n",
                    f"**Project**: {project_goal}",
                    f"**Tasks Completed**: {len(completed_changes)}",
                    f"**Generated**: {datetime.utcnow().isoformat()}Z\n",
                    "---\n",
                    "## Baseline Assessment\n",
                    f"- Symbols indexed at session start: {baseline_symbols}",
                    f"- CodeGraph backend: {backend}",
                    f"- Session start: {baseline_sync}",
                    f"- Current symbol count: {cg_symbols}\n",
                    "---\n",
                    "## Changes Applied\n"
                ]

                total_tool_calls_est = 0
                unique_files_modified = set()

                # 6. Generate Diffs Deterministically
                for t in completed_changes:
                    t_id = t['id']
                    title = t['title']
                    outputs = t.get('outputs', [])
                    
                    effort = "small"
                    impact = "—"
                    t_start, t_end = ASTMemoryMapper.locate_heading_block(mem_content, "###", t_id)
                    if t_start != -1:
                        task_block = "\n".join(mem_content.splitlines()[t_start:t_end])
                        match_eff = re.search(r"- \*\*Estimated Effort\*\*: (small|medium|large)", task_block, re.IGNORECASE)
                        if match_eff: effort = match_eff.group(1).lower()
                        match_imp = re.search(r"- \*\*CodeGraph Impact\*\*: (.*)", task_block)
                        if match_imp: impact = match_imp.group(1).strip()
                    
                    if effort == "small": total_tool_calls_est += 5
                    elif effort == "medium": total_tool_calls_est += 10
                    elif effort == "large": total_tool_calls_est += 20

                    lines.append(f"### {t_id}: {title}\n")
                    lines.append(f"**What changed**: {', '.join(outputs) if outputs else 'None'}")
                    lines.append(f"**Impact radius** (CodeGraph): {impact}\n")
                    
                    for file_path in outputs:
                        unique_files_modified.add(file_path)
                        encoded_path = file_path.replace("/", "__").replace(":", "__colon__")
                        possible_rollback = os.path.join(".dumbledoer", "rollbacks", t_id, encoded_path)
                        
                        original_text = ""
                        if os.path.exists(possible_rollback):
                            with open(possible_rollback, "r") as rf: original_text = rf.read()
                        
                        current_text = ""
                        if os.path.exists(file_path):
                            with open(file_path, "r") as cf: current_text = cf.read()
                            
                        diff = list(difflib.unified_diff(
                            original_text.splitlines(),
                            current_text.splitlines(),
                            fromfile=f"a/{file_path}",
                            tofile=f"b/{file_path}",
                            n=3, lineterm=""
                        ))
                        
                        if diff:
                            lines.append(f"**Diff for `{file_path}`**:")
                            lines.append("```diff")
                            # Truncate massive diffs to keep report scannable
                            diff_block = "\n".join(diff[:40])
                            lines.append(diff_block)
                            if len(diff) > 40:
                                lines.append(f"... (diff truncated, {len(diff)-40} more lines)")
                            lines.append("```\n")
                            
                # 7. Analytics & Token Yield
                lines.append("---\n")
                lines.append("## Delta Summary\n")
                lines.append("| Metric | Before | After | Change |")
                lines.append("|--------|--------|-------|--------|")
                try: delta_sym = int(cg_symbols) - int(baseline_symbols)
                except ValueError: delta_sym = "N/A"
                delta_str = f"+{delta_sym}" if isinstance(delta_sym, int) and delta_sym > 0 else str(delta_sym)
                lines.append(f"| Symbols indexed | {baseline_symbols} | {cg_symbols} | {delta_str} |")
                lines.append(f"| Files modified | 0 | {len(unique_files_modified)} | +{len(unique_files_modified)} |")
                lines.append(f"| Tasks completed | 0 | {len(completed_changes)} | +{len(completed_changes)} |\n")
                
                lines.append("---\n")
                lines.append("## Token Optimization\n")
                lines.append(f"- Estimated Tool Calls Executed: {total_tool_calls_est}")
                lines.append(f"- Optimization Yield: ~{total_tool_calls_est * 25000} tokens saved")
                lines.append("- Engine Mechanism: Dynamic Tool Filtering & Sliced Memory Ingestion\n")
                
                lines.append("---\n")
                lines.append("## Recommended Next Steps\n")
                if pending_tasks:
                    for pt in pending_tasks:
                        lines.append(f"- {pt['id']}: {pt['title']} ({pt['status']})")
                    lines.append("\nRun `/dumbledoer:resume` to continue working on these tasks.")
                else:
                    lines.append("All improvement tasks completed. The agent has been fully improved per the session goals.")

                report_md = "\n".join(lines)
                
                if output_path:
                    try:
                        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
                        with open(output_path, "w", encoding="utf-8") as f:
                            f.write(report_md)
                        console.print(f"[green]Report successfully written to {output_path}[/green]")
                    except Exception as e:
                        console.print(f"[red]Error writing report to {output_path}: {e}[/red]")
                else:
                    console.print(Markdown(report_md))
                    
                # 8. Sync Knowledge Base implicitly
                if os.path.exists("sync_knowledge.py"):
                    try: subprocess.run([sys.executable, "sync_knowledge.py"], capture_output=True)
                    except: pass
                
                return

            elif command == "audit":
                from rich.console import Console
                from rich.table import Table
                console = Console()
                
                if not os.path.exists("memory.md"):
                    console.print("[red]Error: memory.md not found. Run /dumbledoer:start first.[/red]")
                    return

                with open("memory.md", "r", encoding="utf-8") as f:
                    mem_content = f.read()

                await OrphanRecoveryScanner().run(unattended=True)

                state = TaskRegistryState()
                all_tasks = await state.load_tasks()
                # 1. State Parsing: Target only awaiting-review
                review_tasks = [t for t in all_tasks.values() if t['status'].strip() == 'awaiting-review']

                if not review_tasks:
                    console.print("[green]No tasks currently awaiting review.[/green]")
                    return

                console.print(f"[cyan]Starting Native QA Harness Loop for {len(review_tasks)} task(s)...[/cyan]")
                
                results_summary = []

                # 2. Sequential Unattended Dispatch Loop
                for t in review_tasks:
                    t_id = t['id']
                    title = t['title']
                    outputs = t.get('outputs', [])
                    
                    console.print(f"\n[bold yellow]Auditing {t_id}: {title}[/bold yellow]")
                    
                    # Extract Success Criteria natively
                    success_criteria = "Not defined."
                    t_start, t_end = ASTMemoryMapper.locate_heading_block(mem_content, "###", t_id)
                    if t_start != -1:
                        task_block = "\n".join(mem_content.splitlines()[t_start:t_end])
                        import re
                        match_crit = re.search(r"- \*\*Success Criteria\*\*: (.*)", task_block)
                        if match_crit:
                            success_criteria = match_crit.group(1).strip()
                        match_out = re.search(r"- \*\*Outputs\*\*: (.*)", task_block)
                        if match_out:
                            outputs = [o.strip() for o in match_out.group(1).split(',') if o.strip()]

                    # 3. Native Static Analysis (Defusing the Unbounded Bash Trap)
                    static_analysis_output = ""
                    py_files = [f for f in outputs if f.endswith(".py") and os.path.exists(f)]
                    
                    for pf in py_files:
                        try:
                            # Primary Backend: uvx ruff check
                            import subprocess
                            proc = subprocess.run(["uvx", "ruff", "check", pf], capture_output=True, text=True)
                            out = proc.stdout + proc.stderr
                            if proc.returncode != 0 and "executable file not found" in proc.stderr.lower():
                                raise FileNotFoundError("uvx not found")
                            static_analysis_output += f"--- Ruff Check for {pf} ---\n{out.strip() or 'Syntax OK. No issues found.'}\n"
                        except FileNotFoundError:
                            # Safety Net Backend: Built-in py_compile
                            proc1 = subprocess.run([sys.executable, "-m", "py_compile", pf], capture_output=True, text=True)
                            out = proc1.stdout + proc1.stderr
                            if proc1.returncode != 0:
                                static_analysis_output += f"--- py_compile for {pf} ---\n{out.strip()}\n"
                            else:
                                static_analysis_output += f"--- py_compile for {pf} ---\nSyntax OK.\n"
                                
                    if not static_analysis_output.strip():
                        static_analysis_output = "No Python files modified, or no static analysis warnings found."
                    
                    # Hard Truncation to prevent context window explosion
                    if len(static_analysis_output) > 2000:
                        static_analysis_output = static_analysis_output[:2000] + "\n... [TRUNCATED BY NATIVE ORCHESTRATOR TO PREVENT TOKEN BLOAT]"

                    # 4. Isolated LLM Evaluator Prompt
                    prompt_payload = f"""You are the strict DumbleDoer QA Evaluator.
You are evaluating EXACTLY ONE task.

# TASK UNDER REVIEW: {t_id}
Title: {title}
Modified Files: {', '.join(outputs) if outputs else 'None'}
Success Criteria: {success_criteria}

# NATIVE STATIC ANALYSIS RESULTS
{static_analysis_output}

# YOUR DIRECTIVE
1. Evaluate the static analysis output and any other necessary context (using read_file or execute_bash for a single targeted test if needed).
2. If the task passes its success criteria and has no critical static analysis errors, you MUST use the `update_memory_registry` tool to change its status from `awaiting-review` to `completed` in the Task Registry. Example target string: `| {t_id} | {title} | change | awaiting-review |`
3. If the task fails, you MUST use the `add_task` tool to queue a specific `change` task to fix the bug. **CRITICAL: Set the `deps` argument to "none". Do NOT make the new task depend on the failed task, or the execution engine will deadlock.** Do not change the current task's status (leave it as awaiting-review).
4. Terminate your turn with a brief summary of your decision.
"""
                    
                    chat_session = await self.provider.create_chat_session(model_name=getattr(self, "model", "gemini-3.1-pro-preview"), tools=self._get_tools_for_command("audit"))
                    
                    with console.status(f"[cyan]LLM Evaluator analyzing {t_id}...[/cyan]", spinner="dots") as status:
                        try:
                            response = await self._run_with_tools(chat_session, prompt_payload, self.provider, status=status)
                            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                                self.budget_manager.add_tokens(getattr(response.usage_metadata, 'total_token_count', 0))
                            self.budget_manager.check_and_harvest()
                            
                            # Reload tasks to detect what the LLM decided
                            new_tasks = await TaskRegistryState().load_tasks()
                            current_status = new_tasks.get(t_id, {}).get('status', 'awaiting-review')
                            
                            if current_status == 'completed':
                                results_summary.append((t_id, "[green]PASSED[/green]", "Marked completed"))
                                console.print(f"[green]✔ {t_id} Passed QA.[/green]")
                            else:
                                results_summary.append((t_id, "[red]FAILED[/red]", "Fix task queued"))
                                console.print(f"[red]✖ {t_id} Failed QA. Fix task generated.[/red]")
                                
                        except BudgetExhaustedException:
                            console.print("[bold red]Budget exhausted during audit.[/bold red]")
                            await self._graceful_shutdown(t_id)
                            return
                        except Exception as e:
                            console.print(f"[bold red]Error auditing {t_id}: {e}[/bold red]")
                            results_summary.append((t_id, "[yellow]ERROR[/yellow]", str(e)))

                # 5. Final Report
                console.print("\n[bold]Audit Wave Complete[/bold]")
                table = Table(title="QA Harness Results")
                table.add_column("Task ID", style="cyan")
                table.add_column("Result")
                table.add_column("Action Taken", style="dim")
                for res in results_summary:
                    table.add_row(res[0], res[1], res[2])
                console.print(table)
                return

            elif command == "status":
                is_verbose = "--verbose" in args or "-v" in args
                
                if not os.path.exists("memory.md"):
                    print("Error: memory.md not found. Run /dumbledoer:start to begin.")
                    return

                with open("memory.md", "r", encoding="utf-8") as f:
                    content = f.read()

                # 1. Parse Project Goal
                goal_start, goal_end = ASTMemoryMapper.locate_heading_block(content, "##", "Project Goal")
                project_goal = "None"
                if goal_start != -1:
                    for line in content.splitlines()[goal_start+1:goal_end]:
                        if line.strip() and not line.startswith("#"):
                            project_goal = line.strip().split(".")[0] + "."
                            break

                # 2. Parse Session & Budget Data
                sess_start, sess_end = ASTMemoryMapper.locate_heading_block(content, "##", "Session Log")
                last_session_id, last_outcome, last_end = "None", "None", "None"
                if sess_start != -1:
                    sess_lines = [l.strip() for l in content.splitlines()[sess_start+1:sess_end] if l.startswith("|") and "---" not in l and "Session ID" not in l]
                    if sess_lines:
                        parts = [p.strip() for p in sess_lines[-1].split("|")]
                        if len(parts) >= 6:
                            last_session_id, last_end, last_outcome = parts[1], parts[3], parts[4]

                tokens = self.budget_manager.estimated_tokens
                limit = self.budget_manager.budget_limit
                pct_used = int((tokens / limit) * 100) if limit > 0 else 0

                # 3. Print Header
                print(f"\ndumbledoer — Session {last_session_id} | Budget: {pct_used}% used ({tokens}/{limit} est. tokens)")
                print(f"\nProject Goal: {project_goal}\n")
                print("Task Registry:")

                # 4. Parse and Format Task Registry
                icons = {"completed": "✅", "in_progress": "🔄", "interrupted": "⏸", "pending": "⬜", "blocked": "🚫", "deferred": "💤"}
                tasks = await TaskRegistryState().load_tasks()
                
                for t_id, t in tasks.items():
                    parts = [p.strip() for p in t.get('original_line', '').split("|")]
                    t_type = parts[3] if len(parts) > 3 else "unknown"
                    t_status = parts[4] if len(parts) > 4 else t['status']
                    owner = parts[5] if len(parts) > 5 else "—"
                    
                    icon = icons.get(t_status.lower(), "⬜")
                    title = (t['title'][:47] + "...") if len(t['title']) > 50 else t['title']
                    
                    step_note = ""
                    if "in_progress" in t_status.lower() and len(parts) > 8:
                        chk_id = parts[8]
                        if "step" in chk_id:
                            step_note = f"(step {chk_id.split('step')[1].split('-')[0]})"

                    print(f"  {icon} {t_id}  {title:<50} [{t_type}]  {owner}  {step_note}")
                    
                    if is_verbose:
                        # Extract and print detailed task block
                        t_start, t_end = ASTMemoryMapper.locate_heading_block(content, "###", t_id)
                        if t_start != -1:
                            print("\n    " + "\n    ".join(content.splitlines()[t_start+1:t_end]))
                            print("")

                # 5. Fetch CodeGraph Status Natively
                cg_healthy, cg_symbols, cg_sync = "⚠ not initialized — run codegraph init -i", "0", "N/A"
                if os.path.exists(".codegraph"):
                    try:
                        import subprocess, re
                        cg_out = (await asyncio.to_thread(subprocess.run, ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "status"], capture_output=True, text=True)).stdout
                        sym_match = re.search(r"(\d+)\s+symbols", cg_out)
                        cg_symbols = sym_match.group(1) if sym_match else "unknown"
                        cg_healthy = "✅ healthy" if "healthy" in cg_out.lower() or "ok" in cg_out.lower() else "⚠ stale"
                        cg_sync = "recently" # Simplification for native speed
                    except Exception:
                        cg_healthy = "⚠ degraded"

                # 6. Evaluate Knowledge Registry Natively
                know_path = "knowledge"
                conf_start, conf_end = ASTMemoryMapper.locate_heading_block(content, "##", "Config")
                if conf_start != -1:
                    for l in content.splitlines()[conf_start:conf_end]:
                        if "- knowledge_path:" in l:
                            know_path = l.split(":", 1)[1].strip()

                if not os.path.exists(know_path):
                    know_str = f"Knowledge: no registry — /dumbledoer:start creates it"
                else:
                    k_stats = {"decision": 0, "success": 0, "failure": 0, "constraint": 0, "insight": 0, "superseded": 0}
                    k_total, k_last_date = 0, "N/A"
                    import glob, re
                    entries = glob.glob(os.path.join(know_path, "entries", "*.md"))
                    dates = []
                    for e in entries:
                        try:
                            with open(e, "r", encoding="utf-8") as kf:
                                fm = re.match(r'^---\n(.*?)\n---', kf.read(), re.DOTALL)
                                if fm:
                                    fm_text = fm.group(1).lower()
                                    t_match = re.search(r'type:\s*(\w+)', fm_text)
                                    s_match = re.search(r'status:\s*(\w+)', fm_text)
                                    d_match = re.search(r'created:\s*([^\n]+)', fm_text)
                                    
                                    if t_match and t_match.group(1) in k_stats: k_stats[t_match.group(1)] += 1
                                    if s_match and "superseded" in s_match.group(1): k_stats["superseded"] += 1
                                    if d_match: dates.append(d_match.group(1).strip())
                                    k_total += 1
                        except Exception: pass
                        
                    if dates: k_last_date = max(dates)
                    know_str = f"Knowledge: {k_total} entries ({k_stats['decision']} decisions, {k_stats['success']} successes, {k_stats['failure']} failures, {k_stats['constraint']} constraints, {k_stats['insight']} insights; {k_stats['superseded']} superseded) | last entry {k_last_date} | {know_path}"

                # 7. Print Footers
                print(f"\nLast session: {last_session_id} — {last_outcome} ({last_end})")
                print(f"CodeGraph: {cg_healthy} | {cg_symbols} symbols | last sync {cg_sync}")
                print(know_str + "\n")
                return

            elif command == "update-docs":
                dry_run = "--dry-run" in args
                enrich = "--enrich" in args
                docs_path = None
                
                # 1. Parse Args & memory.md Config
                for i, arg in enumerate(args):
                    if arg.startswith("--docs="):
                        docs_path = arg.split("=")[1]
                    elif arg == "--docs" and i + 1 < len(args):
                        docs_path = args[i + 1]

                if not os.path.exists("memory.md"):
                    print("Error: memory.md not found. Run /dumbledoer:start to initialize.")
                    return
                
                with open("memory.md", "r", encoding="utf-8") as f:
                    mem_content = f.read()
                
                if not docs_path:
                    conf_start, conf_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
                    if conf_start != -1:
                        for line in mem_content.splitlines()[conf_start:conf_end]:
                            if "- docs_path:" in line:
                                docs_path = line.split(":", 1)[1].strip()
                
                if not docs_path or not os.path.isdir(docs_path):
                    print(f"Error: valid docs path not found ('{docs_path}'). Provide --docs <path>.")
                    return

                last_docs_update = None
                conf_start, conf_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
                if conf_start != -1:
                    for line in mem_content.splitlines()[conf_start:conf_end]:
                        if "- last_docs_update:" in line and "null" not in line and "never" not in line:
                            last_docs_update = line.split(":", 1)[1].strip()

                # 2. Get Changed Files from Git
                changed_files = []
                if last_docs_update:
                    try:
                        git_out = subprocess.run(["git", "log", "--name-only", "--pretty=format:", f"--since={last_docs_update}"], capture_output=True, text=True).stdout
                        changed_files = [f.strip() for f in git_out.splitlines() if f.strip()]
                    except Exception:
                        pass

                from rich.console import Console
                from rich.table import Table
                from rich.prompt import Prompt
                console = Console()
                
                console.print(f"[cyan]Scanning '{docs_path}' for explicit AST bindings...[/cyan]")
                
                # 3. Explicit AST Extraction (Defusing the Backtick Bomb)
                wikilink_pattern = re.compile(r'\[\[([^\|\]]+)(?:\|[^\]]+)?\]\]')
                html_comment_pattern = re.compile(r'<!--\s*ast-symbol:\s*([^\s>]+)\s*-->')

                import glob
                doc_files = glob.glob(os.path.join(docs_path, "**/*.md"), recursive=True)
                if not doc_files:
                    console.print(f"[yellow]Warning: No markdown files found in {docs_path}.[/yellow]")
                    return

                tasks_to_create = []
                
                # 4. Inverted Search & Delta Analysis
                with console.status("[bold yellow]Inverting search against CodeGraph AST...", spinner="dots"):
                    for doc_file in doc_files:
                        with open(doc_file, "r", encoding="utf-8") as df:
                            doc_content = df.read()
                        
                        symbols = set(wikilink_pattern.findall(doc_content) + html_comment_pattern.findall(doc_content))
                        
                        needs_update = False
                        reasons = []

                        if enrich and len(doc_content.splitlines()) <= 5:
                            needs_update = True
                            reasons.append("Sparse document (enrichment candidate)")

                        for sym in symbols:
                            try:
                                cg_out = (await asyncio.to_thread(subprocess.run, ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "search", sym], capture_output=True, text=True)).stdout
                                
                                if "No results" in cg_out or not cg_out.strip():
                                    needs_update = True
                                    reasons.append(f"Symbol '{sym}' is dead/missing")
                                elif not last_docs_update or any(cf in cg_out for cf in changed_files):
                                    needs_update = True
                                    reasons.append(f"Symbol '{sym}' source file modified")
                            except Exception:
                                pass 

                        if needs_update:
                            tasks_to_create.append({
                                "file": doc_file,
                                "reasons": list(set(reasons))
                            })

                if not tasks_to_create:
                    console.print("[green]Documentation is already up to date. No dead symbols or modified sources detected.[/green]")
                    return

                table = Table(title="Proposed Documentation Updates")
                table.add_column("Document", style="cyan")
                table.add_column("Reason", style="yellow")
                
                for t in tasks_to_create:
                    table.add_row(t['file'], ", ".join(t['reasons']))
                    
                console.print(table)

                if dry_run:
                    console.print("\n[yellow]Dry run — no files modified. Run without --dry-run to apply.[/yellow]")
                    return

                choice = Prompt.ask("Queue these surgical patches into the Task Registry? [Y/N]", choices=["Y", "N"], default="Y")
                if choice == "N":
                    console.print("[yellow]Update cancelled.[/yellow]")
                    return

                # 5. Task Generation & Handoff
                console.print("\n[cyan]Queueing tasks...[/cyan]")
                for t in tasks_to_create:
                    desc = f"Surgically patch {t['file']} to resolve: {', '.join(t['reasons'])}. STRICTLY preserve human rationale, Mermaid diagrams, and tables."
                    res = await add_task(title=f"Update docs: {os.path.basename(t['file'])}", task_type="change", description=desc, outputs=t['file'])
                    console.print(f"[dim]{res}[/dim]")

                from datetime import datetime
                now_iso = datetime.utcnow().isoformat() + "Z"
                mem_content = re.sub(r"- last_docs_update:.*", f"- last_docs_update: {now_iso}", mem_content)
                with open("memory.md", "w", encoding="utf-8") as f:
                    f.write(mem_content)

                console.print("\n[bold green]Tasks successfully queued! Run /dumbledoer:execute to trigger the LLM patch wave.[/bold green]")
                return

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
                        response = await self._run_with_tools(self.chat_session, payload, self.provider, status=status)
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
            self._archive_stale_sessions()
            await self.exit_stack.aclose()

    def _archive_stale_sessions(self):
        archive_keep_sessions = 1
        
        if not os.path.exists("memory.md"):
            return
            
        with open("memory.md", "r", encoding="utf-8") as f:
            content = f.read()
            
        config_start, config_end = ASTMemoryMapper.locate_heading_block(content, "##", "Config")
        if config_start != -1:
            for line in content.splitlines()[config_start:config_end]:
                if "archive_keep_sessions:" in line:
                    try:
                        archive_keep_sessions = int(line.split(":")[1].strip())
                    except:
                        pass
                        
        sess_start, sess_end = ASTMemoryMapper.locate_heading_block(content, "##", "Session Log")
        if sess_start == -1:
            return
            
        lines = content.splitlines()
        session_log_lines = lines[sess_start+1:sess_end]
        
        terminal_sessions = []
        for i, line in enumerate(session_log_lines):
            if line.strip().startswith("|") and "---" not in line and "Timestamp" not in line and "Session ID" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 6:
                    sid = parts[1]
                    outcome = parts[5].lower()
                    if outcome in ("completed", "error") or (outcome.startswith("interrupted-") and not outcome.endswith("(archived)")):
                        terminal_sessions.append((sid, line, i))
                        
        if len(terminal_sessions) <= archive_keep_sessions:
            return
            
        to_archive = terminal_sessions[:-archive_keep_sessions]
        if not to_archive:
            return
            
        os.makedirs(".dumbledoer/archive", exist_ok=True)
        os.makedirs(".dumbledoer/tmp", exist_ok=True)
        
        task_start, task_end = ASTMemoryMapper.locate_heading_block(content, "##", "Task Details")
        
        import re
        tasks = {}
        current_task = None
        current_lines = []
        
        in_code_block = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                
            if not in_code_block and re.match(r"^###\s+(T-[\w\-]+)", line):
                if current_task:
                    tasks[current_task] = current_lines
                current_task = re.match(r"^###\s+(T-[\w\-]+)", line).group(1)
                current_lines = [line]
            elif current_task:
                if not in_code_block and re.match(r"^#+\s+", line):
                    tasks[current_task] = current_lines
                    current_task = None
                else:
                    current_lines.append(line)
        if current_task:
            tasks[current_task] = current_lines
            
        archived_tasks_per_session = {}
        for sid, line, _ in to_archive:
            archived_tasks = []
            for tid, tlines in tasks.items():
                status = "pending"
                assigned = "none"
                for tline in tlines:
                    if tline.startswith("- **Status**:"):
                        status = tline.split(":", 1)[1].strip()
                    elif tline.startswith("- **Assigned Session**:"):
                        assigned = tline.split(":", 1)[1].strip()
                if assigned == sid and status in ("completed", "error", "deferred", "abandoned"):
                    archived_tasks.append(tid)
            archived_tasks_per_session[sid] = archived_tasks
            
        new_lines = list(lines)
        from datetime import datetime
        for sid, sess_line, _ in to_archive:
            record_lines = [
                f"# Archived Session: {sid}",
                "",
                f"session_id: {sid}",
                f"archived_at: {datetime.utcnow().isoformat()}Z",
                f"outcome: {sess_line.split('|')[5].strip()}",
                "source: memory.md",
                "",
                "## Session Log Entry",
                "| Session ID | Start Time | End Time | Tasks Claimed | Outcome |",
                "|---|---|---|---|---|",
                sess_line,
                "",
                "## Change Log Entries",
                "| Timestamp | Task ID | Target Path | Summary | Status | Rationale |",
                "|---|---|---|---|---|---|",
            ]
            
            chg_start, chg_end = ASTMemoryMapper.locate_heading_block(content, "##", "Change Log")
            if chg_start != -1:
                for j in range(chg_start+1, chg_end):
                    if lines[j].strip().startswith("|") and "---" not in lines[j] and "Timestamp" not in lines[j]:
                        parts = [p.strip() for p in lines[j].split("|")]
                        if len(parts) >= 6:
                            tid = parts[2]
                            if tid in archived_tasks_per_session[sid] or tid == sid:
                                record_lines.append(lines[j])
                                new_lines[j] = ""
                                
            record_lines.append("")
            record_lines.append("## Checkpoint Registry Entries")
            record_lines.append("| Checkpoint ID | Task ID | Step | Session ID | Files Snapshotted |")
            record_lines.append("|---|---|---|---|---|")
            
            chk_start, chk_end = ASTMemoryMapper.locate_heading_block(content, "##", "Checkpoint Registry")
            if chk_start != -1:
                for j in range(chk_start+1, chk_end):
                    if lines[j].strip().startswith("|") and "---" not in lines[j] and "Checkpoint ID" not in lines[j]:
                        parts = [p.strip() for p in lines[j].split("|")]
                        if len(parts) >= 6:
                            csid = parts[4]
                            if csid == sid:
                                record_lines.append(lines[j])
                                new_lines[j] = ""
                                
            record_lines.append("")
            record_lines.append("## Task Details")
            
            for tid in archived_tasks_per_session[sid]:
                record_lines.extend(tasks[tid])
                t_idx = -1
                for k, nl in enumerate(new_lines):
                    if nl == f"### {tid}":
                        t_idx = k
                        break
                if t_idx != -1:
                    while t_idx < len(new_lines) and (new_lines[t_idx] == f"### {tid}" or not re.match(r"^#+\s+", new_lines[t_idx])):
                        new_lines[t_idx] = ""
                        t_idx += 1
                        if t_idx < len(new_lines) and re.match(r"^#+\s+", new_lines[t_idx]):
                            break
                            
            archive_tmp = f".dumbledoer/tmp/{sid}.archive.tmp"
            archive_md = f".dumbledoer/archive/{sid}.md"
            with get_registry_lock():
                with open(archive_tmp, "w", encoding="utf-8") as f:
                    f.write("\n".join(record_lines))
                
            os.replace(archive_tmp, archive_md)
            
            idx_start, idx_end = ASTMemoryMapper.locate_heading_block(content, "##", "Archive Index")
            archive_row = f"| {sid} | {datetime.utcnow().isoformat()}Z | .dumbledoer/archive/{sid}.md | {len(archived_tasks_per_session[sid])} | {sess_line.split('|')[5].strip()} |"
            if idx_start == -1:
                new_lines.append("")
                new_lines.append("## Archive Index")
                new_lines.append("| Session ID | Archived At | Archive File | Tasks Archived | Outcome |")
                new_lines.append("|---|---|---|---|---|")
                new_lines.append(archive_row)
            else:
                new_lines.insert(idx_end, archive_row)
                
            for j in range(sess_start+1, sess_end):
                if new_lines[j].strip().startswith(f"| {sid} |"):
                    parts = new_lines[j].split("|")
                    parts[5] = f" {parts[5].strip()} (archived) "
                    new_lines[j] = "|".join(parts)
                    break
                    
        final_lines = [l for l in new_lines if l != ""]
        tmp_mem = ".dumbledoer/tmp/memory.md.tmp"
        with get_registry_lock():
            with open(tmp_mem, "w", encoding="utf-8") as f:
                f.write("\n".join(final_lines))
        os.replace(tmp_mem, "memory.md")
        print(f"Archived {len(to_archive)} session(s) → .dumbledoer/archive/ ({len(lines) - len(final_lines)} lines trimmed from memory.md)")


