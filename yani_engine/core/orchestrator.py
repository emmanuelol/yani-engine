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

        # Sub-components: extracted execution and prompt logic
        from yani_engine.core.agent_loop import AgentRunner
        from yani_engine.core.prompt_builder import PromptBuilder
        self.agent_runner = AgentRunner(self)
        self.prompt_builder = PromptBuilder(self)


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

    async def run(self, command: str, args: list):
        if command in ["iterate", "audit", "start"] and not getattr(config, "model_overridden", False):
            self.model = config.model_heavy
        elif not getattr(config, "model_overridden", False):
            self.model = config.model_fast
        print(f"yani-engine running command: {command}")

        from yani_engine.core.telemetry import init_telemetry, shutdown_telemetry, trace_span

        init_telemetry(
            service_name="yani-engine",
            enable_telemetry=getattr(config, "enable_telemetry", False),
            otlp_endpoint=getattr(config, "otlp_endpoint", None),
            log_format=getattr(config, "log_format", "console"),
            debug=getattr(config, "verbose", False),
        )

        if command == "resume":
            from yani_engine.commands.resume_handler import handle_resume
            result = await handle_resume(self, args)
            if result != "execute":
                return
            command = "execute"

        # Skip MCP initialization for commands that do not need structural code analysis or semantic search
        if command not in ("status", "rollback", "report"):
            from yani_engine.core.mcp_manager import connect_mcp
            await connect_mcp(self)

        try:
            async with trace_span("command.execute", {"command.name": command}):
                if command == "rollback":
                    from yani_engine.commands.handlers import handle_rollback
                    await handle_rollback(self, args)
                elif command == "execute":
                    from yani_engine.core.executor import WaveExecutor
                    await WaveExecutor(self).execute_pending_waves(args)
                elif command == "report":
                    from yani_engine.commands.handlers import handle_report
                    await handle_report(self, args)
                elif command == "audit":
                    from yani_engine.commands.audit_handler import handle_audit
                    await handle_audit(self, args)
                elif command == "update-docs":
                    from yani_engine.commands.docs_handler import handle_update_docs
                    await handle_update_docs(self, args)
                elif command == "iterate":
                    from yani_engine.commands.llm_handlers import handle_iterate
                    await handle_iterate(self, args)
                elif command == "status":
                    from yani_engine.commands.handlers import handle_status
                    await handle_status(self, args)
                elif command == "start":
                    from yani_engine.commands.llm_handlers import handle_start
                    await handle_start(self, args)
                else:
                    print(f"Error: Unknown command '{command}'")
        finally:
            from yani_engine.core.sandbox import _teardown_warm_sandbox
            from yani_engine.core.archiver import archive_stale_sessions

            await _teardown_warm_sandbox()
            if command not in ["status", "report"]:
                await archive_stale_sessions()

            if hasattr(self, "providers"):
                for provider in self.providers.values():
                    if hasattr(provider, "aclose"):
                        await provider.aclose()

            await self.exit_stack.aclose()
            shutdown_telemetry()
