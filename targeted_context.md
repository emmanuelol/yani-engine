### SYSTEM INSTRUCTIONS ###
CURRENT GIT BRANCH: `main`
TARGET FILE: `dumbledoer/core/sandbox.py`

ROLE: Act as my Principal Software Engineer, Site Reliability Architect (SRE), and Chaos Engineer.
OBJECTIVE: Conduct a deep code audit and scientific debugging of the provided module.
RULES:
1. Boundary Analysis: Cross-reference the code with callers/callees. Do not break contracts.
2. Chaos Engineering: Assume network fails or DB drops. Ensure idempotency.
3. Zero Quick Patches: Track down the root cause and explain the logical flaw.
4. Branch Context: Ensure any proposed fixes or architectural plans align with the purpose of the current Git branch.

EXPECTED OUTPUT:
(A) Architecture Diagnosis
(B) Risks and Errors (Bugs/Blockers)
(C) Execution Action Plan (Task, Target File, Location, Action, DoD, Validation Method).
###########################

# Arquitectura Objetivo

## Módulos que dependen de este archivo (Callers):
- `test_sdk.py`
- `test_permissions.py`
- `dumbledoer/core/orchestrator.py`

## Dependencias internas (Callees):
- Ninguna.


# Código Fuente

### FILE: dumbledoer/core/sandbox.py
```python
from dumbledoer.core.locks import _MEMORY_MUTEX, _REGISTRY_LOCK, get_registry_lock
import os
import sys
import asyncio
import subprocess
import shutil
import shlex  # <--- NEW: Global import required for run_rtk and execute_bash


def _is_sandbox_warm_sync(worker_id: str) -> bool:
    try:
        import hashlib
        project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
        result = subprocess.run(["docker", "ps", "-q", "-f", f"name=dumbledoer-sandbox-{project_hash}-{worker_id}"], capture_output=True, text=True)
        return bool(result.stdout.strip())
    except Exception:
        return False

async def _ensure_warm_sandbox(task_id: str = None, worker_id: str = None, sandbox_mode: str = "dumbledoer-base") -> bool:
    active_id = worker_id or task_id
    if not active_id: return False
    
    def _do_warm():
        try:
            import hashlib
            project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
            container_name = f"dumbledoer-sandbox-{project_hash}-{active_id}"
            
            # Check if already running
            chk = subprocess.run(["docker", "ps", "-q", "-f", f"name={container_name}"], capture_output=True, text=True)
            if chk.stdout.strip():
                return True
                
            # Ruthlessly purge any exited or crashed containers holding the target name
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)
                
            # Create Shadow Clone Atomically
            shadow_dir = os.path.abspath(f".dumbledoer/shadow_{active_id}")
            shadow_tmp = f"{shadow_dir}.tmp"
            
            if os.path.exists(shadow_tmp):
                shutil.rmtree(shadow_tmp)
            os.makedirs(shadow_tmp, exist_ok=True)
            
            # Remove copy_function=os.link to prevent Hard Link Sandbox Escapes
            ignore_patterns = shutil.ignore_patterns(
                ".git", ".venv", "venv", "env", ".pytest_cache", "__pycache__", 
                "node_modules", ".dumbledoer", ".codegraph", "*.tmp", "*.bak", "shadow_*"
            )
            shutil.copytree(os.getcwd(), shadow_tmp, ignore=ignore_patterns, dirs_exist_ok=True)
            
            # Atomic swap
            if os.path.exists(shadow_dir):
                shutil.rmtree(shadow_dir)
            os.replace(shadow_tmp, shadow_dir)
            
            # --- NEW: Dynamic Target Image Resolution ---
            target_image = "dumbledoer-base:latest"
            
            if sandbox_mode.startswith("docker:"):
                target_image = sandbox_mode.split(":")[1]
            elif sandbox_mode == "auto":
                if os.path.exists(os.path.join(shadow_dir, "Dockerfile")):
                    target_image = f"dumbledoer-custom-{project_hash}"
                    print(f"Building native sandbox from project Dockerfile: {target_image}...")
                    subprocess.run(["docker", "build", "-t", target_image, "."], cwd=shadow_dir, capture_output=True, check=True)
            
            user_map = f"{os.getuid()}:{os.getgid()}"
            subprocess.run(
                ["docker", "run", "--rm", "-d", "-i", 
                 "--user", user_map,
                 "--memory=1500m", "--memory-swap=1500m",  # Strict RAM cap
                 "--name", container_name,
                 "-v", f"{shadow_dir}:/workspace", "-w", "/workspace", 
                 target_image, "/bin/bash"],
                capture_output=True,
                check=True
            )
            
            # Verify it started dynamically
            import time
            for _ in range(5):
                chk2 = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                    capture_output=True, text=True
                )
                if chk2.stdout.strip() == "true":
                    return True
                time.sleep(0.2)
            
            return False
        except Exception as e:
            raise RuntimeError(f"Docker infrastructure failure. Is the daemon running? Details: {e}")
    return await asyncio.to_thread(_do_warm)

async def _teardown_warm_sandbox(task_id: str = None, worker_id: str = None):
    active_id = worker_id or task_id
    if not active_id: return
    def _do_teardown():
        try:
            import hashlib
            project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
            container_name = f"dumbledoer-sandbox-{project_hash}-{active_id}"
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            shadow_dir = os.path.abspath(f".dumbledoer/shadow_{active_id}")
            if os.path.exists(shadow_dir):
                shutil.rmtree(shadow_dir)
        except Exception:
            pass
    await asyncio.to_thread(_do_teardown)

import atexit
import glob

def _cleanup_all_sandboxes():
    try:
        import hashlib
        import os
        project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
        # stop all running dumbledoer-sandbox containers for this project
        res = subprocess.run(["docker", "ps", "-q", "-f", f"name=dumbledoer-sandbox-{project_hash}-"], capture_output=True, text=True, timeout=10)
        if res.stdout.strip():
            for cid in res.stdout.strip().splitlines():
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=10)
        # remove all shadow dirs
        for shadow_dir in glob.glob(".dumbledoer/shadow_*"):
            shutil.rmtree(shadow_dir, ignore_errors=True)
    except Exception:
        pass

atexit.register(_cleanup_all_sandboxes)

async def _safe_async_execute(cmd_args: list, timeout: int = 120, max_bytes: int = 131072) -> str:
    """
    Executes a subprocess asynchronously, draining streams non-blockingly
    to prevent OS pipe buffer deadlocks on massive output.
    """
    try:
        # Launch process with asyncio pipes
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024  # 1MB internal buffer limit to prevent RAM exhaustion
        )
    except Exception as e:
        return f"Error initiating subprocess: {str(e)}"

    async def _drain_stream(stream, stream_name: str) -> tuple[str, bool]:
        output = bytearray()
        truncated = False
        while True:
            # Read in 4KB chunks
            chunk = await stream.read(4096)
            if not chunk:
                break
            
            if len(output) + len(chunk) > max_bytes:
                # Append only up to the max_bytes limit, then stop reading
                output.extend(chunk[:(max_bytes - len(output))])
                truncated = True
                break
                
            output.extend(chunk)
            
        return output.decode('utf-8', errors='replace'), truncated

    stdout_task = asyncio.create_task(_drain_stream(process.stdout, 'stdout'))
    stderr_task = asyncio.create_task(_drain_stream(process.stderr, 'stderr'))

    try:
        # Await process exit with a hard timeout ceiling
        await asyncio.wait_for(process.wait(), timeout=timeout)
        
        stdout_text, stdout_trunc = await stdout_task
        stderr_text, stderr_trunc = await stderr_task
        
        # Format output cleanly
        res = f"STDOUT:\n{stdout_text}"
        if stdout_trunc:
            res += f"\n... [SYSTEM OVERRIDE: {max_bytes} byte limit reached. Truncated.]"
            
        res += f"\nSTDERR:\n{stderr_text}"
        if stderr_trunc:
            res += f"\n... [SYSTEM OVERRIDE: {max_bytes} byte limit reached. Truncated.]"
            
        return res

    except asyncio.TimeoutError:
        # Chaos Engineering: Ruthless termination on timeout
        try:
            process.kill()
        except ProcessLookupError:
            pass # Process already exited
        return f"CRITICAL: Command timed out after {timeout} seconds and was forcefully killed (SIGKILL)."
        
    finally:
        # Cleanup dangling stream readers if killed early
        if not stdout_task.done(): stdout_task.cancel()
        if not stderr_task.done(): stderr_task.cancel()

async def execute_bash(command: str, sandbox_mode: str = "dumbledoer-base", task_id: str = None, worker_id: str = None) -> str:
    # NEW: Dynamically resolve the workspace path based on execution context
    work_dir = os.getcwd() if sandbox_mode == "native" else "/workspace"
    # Remove shlex.quote to prevent Contract Violation in Command Parsing
    env_wrapper = f"export PYTHONPATH={work_dir}:$PYTHONPATH && {command}"
    
    # Process User Mapping
    user_map = f"{os.getuid()}:{os.getgid()}"
    
    # --- APPLY FIX 3: Secure Native Sandbox Execution ---
    if sandbox_mode == "native":
        return await _safe_async_execute(["bash", "-c", env_wrapper], timeout=120)
        
    # --- NEW: Docker Compose Integration ---
    elif sandbox_mode and sandbox_mode.startswith("compose:"):
        service_name = sandbox_mode.split(":")[1]
        return await _safe_async_execute(
            ["docker", "compose", "exec", "-T", "--user", user_map, service_name, "/bin/bash", "-c", env_wrapper],
            timeout=300
        )

    # --- UPDATED: Fallback parsing for 'auto' and 'docker:<image>' ---
    else:
        image = "dumbledoer-base:latest"
        if sandbox_mode and sandbox_mode.startswith("docker:"):
            image = sandbox_mode.split(":")[1]
        elif sandbox_mode == "auto" and os.path.exists("Dockerfile"):
            image = "dumbledoer-custom-fallback"
            await asyncio.to_thread(subprocess.run, ["docker", "build", "-t", image, "."], check=True, capture_output=True, text=True)

        active_id = worker_id or task_id
        if active_id and _is_sandbox_warm_sync(active_id):
            import hashlib
            project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
            container_name = f"dumbledoer-sandbox-{project_hash}-{active_id}"
            
            return await _safe_async_execute(
                ["docker", "exec", "--user", user_map, container_name, "/bin/bash", "-c", env_wrapper],
                timeout=300
            )
        else:
            # Mount as read-write (:rw) so discovery commands (pip install, touch) work.
            # Extended timeout (300s) to support heavy installs.
            import uuid
            ephemeral_dir = os.path.abspath(f".dumbledoer/ephemeral_{uuid.uuid4().hex[:8]}")
            ignore_patterns = shutil.ignore_patterns(
                ".git", ".venv", "venv", "env", ".pytest_cache", "__pycache__", 
                "node_modules", ".dumbledoer", ".codegraph", "*.tmp", "*.bak", "shadow_*"
            )
            shutil.copytree(os.getcwd(), ephemeral_dir, ignore=ignore_patterns, dirs_exist_ok=True)
            
            try:
                return await _safe_async_execute(
                    ["docker", "run", "--rm", 
                     "--user", user_map,
                     "--memory=1500m", "--memory-swap=1500m",
                     "-v", f"{ephemeral_dir}:/workspace:rw", "-w", "/workspace", 
                     image, "/bin/bash", "-c", env_wrapper],
                    timeout=300
                )
            finally:
                if os.path.exists(ephemeral_dir):
                    shutil.rmtree(ephemeral_dir, ignore_errors=True)

async def run_rtk(command: str) -> str:
    rtk_bin = shutil.which("rtk")
    if not rtk_bin:
        cargo_path = os.path.expanduser("~/.cargo/bin/rtk")
        if os.path.exists(cargo_path):
            rtk_bin = cargo_path
        elif os.path.exists("./bin/rtk"):
            rtk_bin = "./bin/rtk"
        else:
            raise RuntimeError("Error: RTK binary not found in standard paths.")

    try:
        args = [rtk_bin] + shlex.split(command)
        result = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error ({e.returncode}):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}")
    except Exception as e:
        raise RuntimeError(f"Exception executing rtk command: {e}")


```

### FILE: test_sdk.py
```python
import sys
sys.path.append('.')
import asyncio
import os
from google import genai
from dumbledoer.core.sandbox import execute_bash

async def test():
    client = genai.Client()
    chat = client.aio.chats.create(model='gemini-2.5-flash')
    response = await chat.send_message(
        'Please run echo hello using execute_bash', 
        config={'tools': [execute_bash], 'automatic_function_calling': {'disable': False}}
    )
    print("Response text:", response.text)
    if hasattr(response, "candidates") and response.candidates:
        if response.candidates[0].content.parts:
            print("Response parts:", [p for p in response.candidates[0].content.parts])

if __name__ == "__main__":
    asyncio.run(test())

```

### FILE: test_permissions.py
```python
import asyncio
import os
import stat
from dumbledoer.core.sandbox import execute_bash

async def test_permissions():
    result = await execute_bash("touch /workspace/test_perm.txt")
    print("Command Output:", result)
    
    file_path = "test_perm.txt"
    if os.path.exists(file_path):
        stat_info = os.stat(file_path)
        print(f"File UID: {stat_info.st_uid}")
        print(f"Host UID: {os.getuid()}")
        if stat_info.st_uid == os.getuid():
            print("SUCCESS: File is owned by the host user.")
        else:
            print("FAILURE: File is NOT owned by the host user.")
    else:
        print("FAILURE: File not found.")

if __name__ == "__main__":
    asyncio.run(test_permissions())

```

### FILE: dumbledoer/core/orchestrator.py
```python
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
    append_handoff_summary, append_session_log_row,
    get_registry_lock, ASTMemoryMapper, 
    update_task_registry_row, CheckpointManager, OrphanRecoveryScanner, 
    TaskRegistryState, read_file, write_file_with_review,
    add_task, read_code_block, record_knowledge, register_task_batch,
    flush_task_registry
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

        self.local_tools = [read_file, read_code_block, write_file_with_review, execute_bash, update_task_registry_row, run_rtk, add_task, register_task_batch, record_knowledge]
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
        "start":   {"read_file", "add_task", "register_task_batch", "write_file_with_review", "execute_bash", "codegraph_*", "context7_*"},
        # STRICT iterate WHITELIST: Blocked add_task to force register_task_batch
        "iterate": {"register_task_batch", "read_file", "read_code_block", "update_task_registry_row", "codegraph_search", "codegraph_impact", "context7_*"},
        # --- NEW EXPLICIT WHITELIST FOR EXECUTE ---
        "execute": {"read_file", "read_code_block", "write_file_with_review", "execute_bash", "update_task_registry_row", "codegraph_*", "context7_*"},
        # ------------------------------------------
        "status":  {"read_file", "execute_bash"},
        "rollback": {"read_file", "execute_bash"},
        "report":  {"read_file", "execute_bash", "update_task_registry_row"},
        "audit":   {"read_file", "read_code_block", "execute_bash", "add_task", "register_task_batch", "update_task_registry_row", "codegraph_*", "context7_*"},
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
        # Connect to codegraph
        try:
            if not os.path.exists(".codegraph"):
                os.makedirs(".codegraph", exist_ok=True)
                import sys
                print("Initializing CodeGraph index...", file=sys.stderr)
                import subprocess
                await asyncio.to_thread(subprocess.run, ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"], check=True)
                
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
        # Flag if the real codegraph tools successfully mounted
        self.is_codegraph_active = any(name.startswith("codegraph_") for name in existing_tools)

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
                            args["sandbox_mode"] = getattr(self, "sandbox_mode", "dumbledoer-base")
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
        from dumbledoer.core.sandbox import _ensure_warm_sandbox
        
        # Read memory.md state atomically under mutex
        mem_content = ""
        try:
            async with _MEMORY_MUTEX:
                async with get_registry_lock():
                    if os.path.exists("memory.md"):
                        with open("memory.md", "r", encoding="utf-8") as f:
                            mem_content = f.read()
        except Exception:
            mem_content = ""

        # Fallback description lookup if omitted
        if not description and mem_content:
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(mem_content, "###", task_id)
            if start_idx != -1:
                first_line = mem_content.splitlines()[start_idx].strip()
                description = first_line.replace(f"### {task_id}", "").lstrip(": ").strip() or f"Task {task_id}"
            else:
                description = f"Task {task_id}"
        elif not description:
            description = f"Task {task_id}"

        # --- NEW: Dynamically parse sandbox_mode from memory.md ---
        self.sandbox_mode = "dumbledoer-base"
        if mem_content:
            config_start, config_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
            if config_start != -1:
                for line in mem_content.splitlines()[config_start:config_end]:
                    if "- sandbox_mode:" in line:
                        self.sandbox_mode = line.split(":", 1)[1].strip()

        print(f"Initializing isolated sandbox ({self.sandbox_mode}) for task {task_id}...")
        
        # Pass the parsed mode to the warm sandbox initiator
        if not self.sandbox_mode.startswith("compose:") and self.sandbox_mode != "native":
            await _ensure_warm_sandbox(worker_id or task_id, sandbox_mode=self.sandbox_mode)
            
        print(f"Executing task {task_id}: {description}")
        
        # Generate session ID and claim task with ownership
        import datetime
        import uuid
        session_id = f"S-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        await update_task_registry_row(task_id, "in_progress", session_id)
        await append_session_log_row(session_id, task_id)
        
        # --- VENDOR-AGNOSTIC TIERING ---
        effort = "small"
        if mem_content:
            import re
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(mem_content, "###", task_id)
            if start_idx != -1:
                task_block = "\n".join(mem_content.splitlines()[start_idx:end_idx])
                match = re.search(r"- \*\*Estimated Effort\*\*: (small|medium|large)", task_block, re.IGNORECASE)
                if match:
                    effort = match.group(1).lower()
            
        # Select the active provider dynamically (preferring the first available if not explicitly requested)
        active_provider = list(self.providers.values())[0]

        # NEW: Route strictly by Capability Tier
        if effort in ["medium", "large"] or getattr(self, "model", config.model_fast) == config.model_heavy:
            target_model = config.model_heavy
            active_provider = self.providers.get("cloud", list(self.providers.values())[0])
            print(f"[Heavy Tier] Task {task_id} ({effort} effort) -> Routing to {target_model}")
        else:
            target_model = config.model_fast
            # Favor the local provider for fast/small tasks to conserve API credits
            active_provider = self.providers.get("local", self.providers.get("cloud", list(self.providers.values())[0]))
            print(f"[Fast Tier] Task {task_id} ({effort} effort) -> Routing to {target_model}")
            
        # Enforce execution whitelist to prevent tool hallucinations
        chat_session = await active_provider.create_chat_session(
            model_name=target_model, 
            tools=self._get_tools_for_command("execute")
        )
        system_instructions = await self._get_system_instructions(command="execute", task_id=task_id)
        
        # --- PRE-LOAD MANDATORY PROTOCOLS TO PREVENT TOOL-CALL BURN ---
        cp_protocol = await read_file(os.path.join(self.plugin_root, 'lib', 'checkpoint-protocol.md'))
        
        if getattr(self, "is_codegraph_active", False):
            cg_protocol = await read_file(os.path.join(self.plugin_root, 'lib', 'codegraph-integration.md'))
            cg_injection = f"# CODEGRAPH INTEGRATION PROTOCOL\n{cg_protocol}"
        else:
            cg_injection = "> **🚨 SYSTEM OVERRIDE: CODEGRAPH OFFLINE 🚨**\n> The structural analysis server is currently unreachable. You are explicitly authorized to BYPASS the 10-step data flow.\n> Rely exclusively on `read_file`, `read_code_block`, and `execute_bash` for codebase discovery."
        
        is_cg_active = getattr(self, "is_codegraph_active", False)
        
        # Conditionally format the strict rules so the LLM doesn't paradox if tools are offline
        if is_cg_active:
            cg_rules = f"""1. You have already been provided the CodeGraph Integration and Checkpoint Protocols. Follow them strictly.
2. Follow the 10-step data flow for change tasks exactly.
3. Log your codegraph_impact result to memory.md task {task_id} CodeGraph Impact field."""
        else:
            cg_rules = """1. CODEGRAPH IS OFFLINE. Bypass the 10-step structural flow. Rely on bash and file reads.
2. Skip codegraph_impact logging.
3. Focus strictly on executing the code modification safely."""

        prompt_payload = f"""{system_instructions}

{cg_injection}

# CHECKPOINT PROTOCOL
{cp_protocol}

You are executing task {task_id}: {description}.

Mandatory rules:
{cg_rules}
4. The `write_file_with_review` tool AUTOMATICALLY handles the entire Checkpoint Protocol for you. Just pass the target file path and final content. Do not manually create rollbacks, tmp files, or checkpoints.
5. Do not modify any file listed in another in_progress task's Outputs.
6. Output compression: render your conversational replies at the appropriate caveman level.
7. Documentation lookup: check if this task involves external dependencies and consult context7 if needed.
8. **DO NOT USE BASH TO PARSE MEMORY.MD.** If you need to read `memory.md`, you MUST use the native `read_file` tool. If you need to update a task status, you MUST use the native `update_task_registry_row` tool. Do not write python scripts via bash to parse the ledger.
9. **STRICT DISCOVERY LIMITATIONS:** You are strictly forbidden from using `execute_bash` to run `find`, `ls`, or `which`. You MUST use `codegraph_search` for discovery.
10. **TOOL CONTEXT:** `run_rtk` is strictly for clearing token cache. NEVER pass python or bash scripts to `run_rtk`.
11. **TEST EXECUTION:** All testing MUST respect the project's native scheduling. Run tests via `uv run pytest` to ensure local `.venv` modules are loaded. A `ModuleNotFoundError` means you are using the wrong environment, not that the file is missing.
12. **NO DUMMY COMMANDS:** You are strictly forbidden from running empty test commands like `echo hello`, `whoami`, or `echo $PATH`. Every bash command must be a meaningful step toward completing the assigned task.
13. **CLEAN UP YOUR ARTIFACTS:** If you create any temporary bash scripts or python files (e.g., `run_test.sh`) to execute multi-line logic, you MUST delete them using `rm` via `execute_bash` immediately after they finish running. Do not leave garbage files in the workspace."""
        # Map the parsed effort level to a safe iteration ceiling
        effort_to_iterations = {
            "small": 15,
            "medium": 25,
            "large": 40,
        }
        max_iters = effort_to_iterations.get(effort, 25)

        try:
            # Parse task type to see if it's a validation task
            task_type = "change"
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(mem_content, "###", task_id)
            if start_idx != -1:
                t_block = "\n".join(mem_content.splitlines()[start_idx:end_idx])
                m_type = re.search(r"- \*\*Type\*\*: (analysis|change|validation|report)", t_block, re.IGNORECASE)
                if m_type:
                    task_type = m_type.group(1).lower()

            # TOKEN-FREE OPTIMIZATION: Bypass LLM agent loop entirely for validation tasks
            if task_type == "validation":
                # --- APPLY FIX 1: Project-Aware Validation Command ---
                test_cmd = "pytest tests/ -v" # Safe baseline fallback
                config_start, config_end = ASTMemoryMapper.locate_heading_block(mem_content, "##", "Config")
                if config_start != -1:
                    for line in mem_content.splitlines()[config_start:config_end]:
                        if "- test_command:" in line:
                            test_cmd = line.split(":", 1)[1].strip()

                print(f"[Deterministic Validator] Task {task_id} is a validation task. Running test suite natively (0 tokens)...")
                print(f"Command: {test_cmd}")
                
                # Execute securely via sandbox
                res = await execute_bash(test_cmd, sandbox_mode=self.sandbox_mode, task_id=task_id)
                print(res)
                
                # --- APPLY FIX 2: Hardened Validation Logic ---
                # Check for explicit failure keywords in the sandbox output
                if "No such file or directory" not in res and "FAILED" not in res and "error" not in res.lower():
                    await update_task_registry_row(task_id, "completed", session_id)
                    print(f"Task {task_id} validated successfully via sandbox run.")
                else:
                    raise RuntimeError("Sandbox validation failed. Test output indicated errors or missing files.")
            else:
                import subprocess
                try:
                    pre_untracked = set(subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True).stdout.splitlines())
                except Exception:
                    pre_untracked = set()

                # Standard LLM tool loop for change/analysis tasks
                response = await self._run_with_tools(chat_session, prompt_payload, active_provider, task_id=task_id, max_iterations=max_iters, worker_id=worker_id)
                self.budget_manager.check_and_harvest()
                
                try:
                    post_untracked = set(subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True).stdout.splitlines())
                    cwd_real = os.path.realpath(os.getcwd())
                    for garbage_file in post_untracked - pre_untracked:
                        abs_path = os.path.realpath(garbage_file)
                        if abs_path.startswith(cwd_real) and os.path.exists(abs_path) and not garbage_file.startswith(".dumbledoer/"):
                            if garbage_file.endswith(".tmp") or garbage_file.endswith(".sh"):
                                print(f"🧹 Purging ephemeral artifact leaked by sandbox: {garbage_file}")
                                os.remove(abs_path)
                except Exception as e:
                    pass

                print(f"Task {task_id} completed: {getattr(response, 'text', str(response))}")
                await update_task_registry_row(task_id, "awaiting-review")
                await flush_task_registry()
        except BudgetExhaustedException:
            print(f"Task {task_id} interrupted: Budget exhausted at {self.budget_manager.estimated_tokens} tokens.", file=sys.stderr)
            await update_task_registry_row(task_id, "interrupted")
            await flush_task_registry()
            await self._graceful_shadow_shutdown(task_id) if hasattr(self, '_graceful_shadow_shutdown') else await self._graceful_shutdown(task_id)
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
                async with _MEMORY_MUTEX:
                    async with get_registry_lock():
                        with open("memory.md", "r", encoding="utf-8") as f:
                            for line in f:
                                parts = [p.strip() for p in line.split("|")]
                                if len(parts) >= 6 and parts[5] == "planned":
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
                
                # --- APPLY FIX 2A: Strict Backup Mapping ---
                # REMOVED the glob.glob() wildcard search here.
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
                    async with _MEMORY_MUTEX:
                        async with get_registry_lock():
                            with open("memory.md", "r", encoding="utf-8") as mem:
                                for line in mem:
                                    parts = [p.strip() for p in line.split("|")]
                                    if len(parts) >= 6 and parts[5] == "planned" and parts[3] == actual_filename:
                                        task_id = parts[2]
                                        break
                                
                if task_id:
                    encoded_path = actual_filename.replace("/", "__").replace(":", "__colon__")
                    possible_rollback = os.path.join(".dumbledoer", "rollbacks", task_id, encoded_path)
                    if os.path.exists(possible_rollback):
                        rollback_path = possible_rollback
                                
                # --- APPLY FIX 2B: Strict Terminal Diff Mapping ---
                # REMOVED the glob.glob() wildcard search here.
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
                async with _MEMORY_MUTEX:
                    async with get_registry_lock():
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
                
                # --- APPLY FIX 2C: Deterministic Rejection Handling ---
                if possible_rollback and os.path.exists(possible_rollback):
                    shutil.copy2(possible_rollback, target_path)
                    rollback_restored = True
                    console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")
                elif os.path.exists(target_path):
                    # If no specific rollback exists, it's a newly created file. Delete it safely.
                    os.remove(target_path)
                    console.print(f"[yellow]Rejected new file creation, deleted {actual_filename}[/yellow]")
                if task_id:
                    await update_task_registry_row(task_id, "pending")
                    await flush_task_registry()
            else:
                # Apply approved change: atomic rename from tmp to target
                if os.path.exists(tmp_path):
                    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
                    await CheckpointManager().atomic_rename_to_target(tmp_path, target_path)
                console.print(f"[green]Approved changes for {actual_filename}[/green]")
                if task_id:
                    await update_task_registry_row(task_id, "completed")
                    await flush_task_registry()
                    # Promote Change Log entry from planned to applied
                    import datetime
                    await CheckpointManager().log_applied_change(target_path, {"Task ID": task_id, "Timestamp": datetime.datetime.now().isoformat()})

        if rejected_files:
            await OrphanRecoveryScanner().run(True)

    async def run(self, command: str, args: list):
        # Restored baseline routing: 'execute' defaults to fast tier.
        # execute_task() will dynamically elevate tasks to heavy tier based on effort.
        # Only force the heavy model if the user didn't explicitly override it via CLI/env
        if command in ["iterate", "audit", "start"] and not getattr(config, "model_overridden", False):
            self.model = config.model_heavy
        elif not getattr(config, "model_overridden", False):
            self.model = config.model_fast
        print(f"DumbleDoer running command: {command}")
        if command == "resume":
            # ADD AWAIT HERE
            await OrphanRecoveryScanner().run()
            
            state = TaskRegistryState()
            tasks = await state.load_tasks()
            
            # Detect interrupted tasks or stale locks natively
            interrupted = [t_id for t_id, t in tasks.items() if t['status'] in ["interrupted", "in_progress", "error"]]
            
            if not interrupted:
                print("\nNo interrupted tasks or stale locks found. Run /dumbledoer:execute to process pending tasks.")
                return
                
            from rich.prompt import Prompt
            from rich.console import Console
            console = Console()
            
            console.print(f"\n[bold yellow]Found interrupted or stale tasks: {', '.join(interrupted)}[/bold yellow]")
            
            # Apply the verbose gate to prevent agent lockups on headless execution
            if config.verbose:
                choice = Prompt.ask("How would you like to handle them? [R(esume)/B(Rollback)/S(Skip)]", choices=["R", "B", "S"], default="R")
            else:
                console.print("[green]Auto-selecting 'Resume' for interrupted tasks (run with -v for interactive options)[/green]")
                choice = "R"
            
            if choice == "B":
                for t_id in interrupted:
                    await update_task_registry_row(t_id, "pending")
                await flush_task_registry()
                console.print("[yellow]Tasks demoted to pending. Please run /dumbledoer:rollback to revert file changes manually.[/yellow]")
                return
            elif choice == "S":
                for t_id in interrupted:
                    await update_task_registry_row(t_id, "deferred")
                await flush_task_registry()
                console.print("[green]Tasks deferred.[/green]")
                return
            else:
                import json
                for t_id in interrupted:
                    # Retrieve the task to find its linked Checkpoint ID
                    task_data = tasks.get(t_id, {})
                    checkpoint_id = task_data.get("checkpoint", "none").strip()
                    
                    if checkpoint_id != "none":
                        chk_path = os.path.join(".dumbledoer", "checkpoints", f"{checkpoint_id}.json")
                        if os.path.exists(chk_path):
                            with open(chk_path, "r") as f:
                                chk_data = json.load(f)
                            # Restore files from the checkpoint JSON
                            for file_path, file_content in chk_data.get("files", {}).items():
                                os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
                                with open(file_path, "w") as tf:
                                    tf.write(file_content)
                            console.print(f"[green]Restored file state from checkpoint {checkpoint_id} for {t_id}[/green]")
                        else:
                            console.print(f"[yellow]Checkpoint {checkpoint_id} referenced by {t_id} not found on disk. Resetting task.[/yellow]")
                    
                    # Clear owner and reset to pending for next wave
                    await update_task_registry_row(t_id, "pending", "—")
                
                console.print("[green]Locks cleared and checkpoints restored. Handing off to execution engine...[/green]")
                
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
                async with _MEMORY_MUTEX:
                    async with get_registry_lock():
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
                    await update_task_registry_row(task_id, "pending")
                await flush_task_registry()

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
                    async with _MEMORY_MUTEX:
                        async with get_registry_lock():
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
                planner = WavePlanner(start_at_index=config.start_at_index, mcp_sessions=self.mcp_sessions)
                
                while True:
                    waves = await planner.get_pending_waves()
                    if not waves:
                        if wave_index == 0:
                            print("No pending tasks to execute.")
                            # NEW: Detect ghosted tasks from a manual kill
                            state = TaskRegistryState()
                            tasks_dict = await state.load_tasks()
                            stuck = [t_id for t_id, t in tasks_dict.items() if t['status'] in ['in_progress', 'interrupted']]
                            if stuck:
                                print(f"⚠ Found tasks stuck in 'in_progress' from a previous aborted run: {', '.join(stuck)}")
                                print("Run '/dumbledoer resume' to safely clear the locks and execute them.")
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

                            async def worker(worker_id: str):
                                while True:
                                    try:
                                        t = queue.get_nowait()
                                    except asyncio.QueueEmpty:
                                        break

                                    # Safely extract task details
                                    task_id = t['id']
                                    task_title = t.get('title', '')

                                    try:
                                        self.budget_manager.check_and_harvest()
                                    except BudgetExhaustedException:
                                        queue.task_done()
                                        while not queue.empty():
                                            queue.get_nowait()
                                            queue.task_done()
                                        break

                                    # Visual Log: Task Claimed / Starting (Routed through progress to prevent UI glitches)
                                    progress.console.print(f"  [bold yellow]🔄 [IN_PROGRESS][/bold yellow] [cyan]{task_id}[/cyan]: {task_title}")

                                    try:
                                        await self.execute_task(task_id, task_title, worker_id=worker_id)
                                        # Visual Log: Task Successfully Completed & Awaiting Review
                                        progress.console.print(f"  [bold green]✅ [AWAITING_REVIEW][/bold green] [cyan]{task_id}[/cyan]: {task_title}")
                                    except BudgetExhaustedException:
                                        progress.console.print(f"  [bold magenta]⏸ [INTERRUPTED][/bold magenta] [cyan]{task_id}[/cyan]: Budget exhausted")
                                        while not queue.empty():
                                            queue.get_nowait()
                                            queue.task_done()
                                        raise
                                    except Exception as e:
                                        # Visual Log: Task Failure
                                        progress.console.print(f"  [bold red]❌ [ERROR][/bold red] [cyan]{task_id}[/cyan]: {e}")
                                        await update_task_registry_row(task_id, "error")
                                        await flush_task_registry()
                                    finally:
                                        progress.advance(wave_task)
                                        queue.task_done()
                                        # NEW: Flush the registry to disk safely as workers finish
                                        from dumbledoer.core.state import flush_task_registry
                                        await flush_task_registry()

                                # Move teardown outside the task loop so it happens per-worker
                                if hasattr(self, 'sandbox_mode') and self.sandbox_mode not in ["native"] and not self.sandbox_mode.startswith("compose:"):
                                    from dumbledoer.core.sandbox import _teardown_warm_sandbox
                                    await _teardown_warm_sandbox(worker_id)

                            # Force a hard-cap of 3 concurrent workers to prevent API token flooding
                            safe_parallel = 3 if max_parallel <= 0 else max_parallel
                            num_workers = min(safe_parallel, len(wave))
                            workers = [asyncio.create_task(worker(f"w{i}")) for i in range(num_workers)]
                            done, pending = await asyncio.wait(workers, return_when=asyncio.FIRST_EXCEPTION)

                            for p in pending:
                                p.cancel()

                            for d in done:
                                if d.exception():
                                    raise d.exception()
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

                async with _MEMORY_MUTEX:
                    async with get_registry_lock():
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
                    
                    # FIX(Task 2): Synchronize QA tracker R/W with a cross-process FileLock
                    # to prevent concurrent audit loops from corrupting attempt history.
                    import json
                    from filelock import FileLock as _FileLock
                    qa_tracker_path = ".dumbledoer/qa_attempts.json"
                    qa_lock_path = qa_tracker_path + ".lock"
                    os.makedirs(os.path.dirname(qa_tracker_path), exist_ok=True)
                    attempts = {}
                    with _FileLock(qa_lock_path, timeout=30):
                        if os.path.exists(qa_tracker_path):
                            with open(qa_tracker_path, "r") as f:
                                attempts = json.load(f)

                        if attempts.get(t_id, 0) >= 3:
                            console.print(f"[red]Task {t_id} has failed QA 3 times. Forcing to deferred to prevent infinite loops.[/red]")
                            await update_task_registry_row(t_id, "deferred")
                            await flush_task_registry()
                            continue

                        attempts[t_id] = attempts.get(t_id, 0) + 1
                        with open(qa_tracker_path, "w") as f:
                            json.dump(attempts, f)

                    # FIX(Task 1): Read memory.md atomically per-task iteration under both
                    # the in-process async mutex and the cross-process registry lock to prevent
                    # stale state reads if another agent mutates the ledger mid-loop.
                    async with _MEMORY_MUTEX:
                        async with get_registry_lock():
                            with open("memory.md", "r", encoding="utf-8") as f:
                                mem_content = f.read()

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
                        import subprocess
                        proc = subprocess.run(["uvx", "ruff", "check", pf], capture_output=True, text=True)
                        out = proc.stdout + proc.stderr
                        if proc.returncode != 0 and "executable file not found" in proc.stderr.lower():
                            static_analysis_output += f"--- Ruff Check for {pf} ---\nCRITICAL ERROR: 'uvx' not found on system. Static analysis failed. Please flag this as a failure.\n"
                        else:
                            static_analysis_output += f"--- Ruff Check for {pf} ---\n{out.strip() or 'Syntax OK. No issues found.'}\n"
                                
                    # Native Test Execution Injection
                    try:
                        if "codegraph" in self.mcp_sessions and py_files:
                            cg_res = await self.mcp_sessions["codegraph"].call_tool("codegraph_affected", arguments={"files": py_files})
                            test_files = cg_res.content[0].text.split(',') if cg_res and cg_res.content else []
                            # FIX(Task 3): Sanitize all file paths with shlex.quote before
                            # shell interpolation to prevent arbitrary command injection.
                            test_files = [shlex.quote(tf.strip()) for tf in test_files if tf.strip()]
                            if test_files:
                                static_analysis_output += f"\n--- Pytest Execution for Affected Tests ---\n"
                                test_proc = await execute_bash(f"pytest {' '.join(test_files)}")
                                static_analysis_output += str(test_proc) + "\n"
                    except Exception as e:
                        pass
                                
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
2. If the task passes its success criteria and has no critical static analysis errors, you MUST use the `update_task_registry_row` tool to change its status to `completed`.
3. If the task fails, you MUST use the `register_task_batch` tool to queue a specific `change` task to fix the bug. CRITICAL: Set the `deps` argument to "none". Do NOT make the new task depend on the failed task, or the execution engine will deadlock. Do not change the current task's status (leave it as awaiting-review). CRITICAL: Set the `estimated_effort` argument to "medium" or "large" (never "small") because fixing bugs requires terminal debugging.
4. Terminate your turn with a brief summary of your decision.
"""
                    
                    chat_session = await self.provider.create_chat_session(model_name=getattr(self, "model", "gemini-3.1-pro-preview"), tools=self._get_tools_for_command("audit"))
                    
                    with console.status(f"[cyan]LLM Evaluator analyzing {t_id}...[/cyan]", spinner="dots") as status:
                        try:
                            # Elevate QA auditor iteration cap to match large tasks
                            response = await self._run_with_tools(chat_session, prompt_payload, self.provider, status=status, task_id=t_id, max_iterations=40)
                            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                                self.budget_manager.add_tokens(getattr(response.usage_metadata, 'total_token_count', 0))
                            else:
                                heuristic_tokens = (len(str(prompt_payload)) // 4) + (len(str(getattr(response, 'text', ''))) // 4)
                                self.budget_manager.add_tokens(heuristic_tokens)
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
                is_verbose = config.verbose or "--verbose" in args or "-v" in args
                
                if not os.path.exists("memory.md"):
                    print("Error: memory.md not found. Run /dumbledoer:start to begin.")
                    return

                from dumbledoer.core.locks import get_registry_lock, _MEMORY_MUTEX
                async with _MEMORY_MUTEX:
                    async with get_registry_lock():
                        with open("memory.md", "r", encoding="utf-8") as f:
                            content = f.read()

                # 1. Parse Project Goal
                goal_start, goal_end = ASTMemoryMapper.locate_heading_block(content, "##", "Project Goal")
                project_goal = "None"
                if goal_start != -1:
                    goal_lines = []
                    for line in content.splitlines()[goal_start+1:goal_end]:
                        l_strip = line.strip()
                        if l_strip and not l_strip.startswith("#"):
                            goal_lines.append(l_strip)
                        elif not l_strip and goal_lines:
                            break
                    if goal_lines:
                        project_goal = " ".join(goal_lines)

                # 2. Parse Session & Budget Data
                sess_start, sess_end = ASTMemoryMapper.locate_heading_block(content, "##", "Session Log")
                last_session_id, last_outcome, last_end = "None", "None", "None"
                if sess_start != -1:
                    sess_lines = [l.strip() for l in content.splitlines()[sess_start+1:sess_end] if l.startswith("|") and "---" not in l and "Session ID" not in l]
                    if sess_lines:
                        parts = [p.strip() for p in sess_lines[-1].split("|")]
                        if len(parts) >= 6:
                            last_session_id, last_end, last_outcome = parts[1], parts[3], parts[5]

                tokens = self.budget_manager.estimated_tokens
                limit = self.budget_manager.budget_limit
                pct_used = int((tokens / limit) * 100) if limit > 0 else 0

                # 3. Print Header
                print(f"\ndumbledoer — Session {last_session_id} | Budget: {pct_used}% used ({tokens}/{limit} est. tokens)")
                print(f"\nProject Goal: {project_goal}\n")
                print("Task Registry:")

                # 4. Parse and Format Task Registry
                icons = {"completed": "✅", "in_progress": "🔄", "interrupted": "⏸", "pending": "⬜", "blocked": "🚫", "deferred": "💤", "awaiting-review": "⏳"}
                tasks = await TaskRegistryState().load_tasks()
                
                archive_index = {}
                if is_verbose:
                    ai_start, ai_end = ASTMemoryMapper.locate_heading_block(content, "##", "Archive Index")
                    if ai_start != -1:
                        for line in content.splitlines()[ai_start+1:ai_end]:
                            if line.strip().startswith("|") and "---" not in line and "Session ID" not in line:
                                ai_parts = [p.strip() for p in line.split("|")]
                                if len(ai_parts) > 4:
                                    archive_index[ai_parts[1]] = ai_parts[3]
                
                for t_id, t in tasks.items():
                    parts = [p.strip() for p in t.get('original_line', '').split("|")]
                    t_type = parts[3] if len(parts) > 3 else "unknown"
                    t_status = parts[4] if len(parts) > 4 else t['status']
                    owner = parts[5] if len(parts) > 5 else "—"
                    
                    icon = icons.get(t_status.lower(), "⬜")
                    title = (t['title'][:47] + "...") if len(t['title']) > 50 else t['title']
                    
                    step_note = ""
                    if ("in_progress" in t_status.lower() or "interrupted" in t_status.lower()) and len(parts) > 8:
                        chk_id = parts[8].strip()
                        if "step" in chk_id:
                            step_parts = chk_id.split('step')
                            if len(step_parts) > 1:
                                try:
                                    step_note = f"(step {step_parts[1].split('-')[0]})"
                                except IndexError:
                                    pass

                    print(f"  {icon} {t_id}  {title:<50} [{t_type}]  {owner}  {step_note}")
                    
                    if is_verbose:
                        if len(parts) > 8 and "archived" in parts[8].lower():
                            archive_file = archive_index.get(owner, f".dumbledoer/archive/{owner}.md")
                            print(f"\n    [Archived] Task details moved to {archive_file}\n")
                        else:
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
                        cg_out = (await asyncio.to_thread(subprocess.run, ["npx", "-y", "--package=@colbymchenry/codegraph", "codegraph", "status"], capture_output=True, text=True, timeout=3)).stdout
                        sym_match = re.search(r"(\d+)\s+symbols", cg_out)
                        cg_symbols = sym_match.group(1) if sym_match else "unknown"
                        cg_healthy = "✅ healthy" if "healthy" in cg_out.lower() or "ok" in cg_out.lower() else "⚠ stale"
                        cg_sync = "recently" # Simplification for native speed
                    except subprocess.TimeoutExpired:
                        cg_healthy = "⚠ stale"
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
                    def _parse_knowledge():
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
                        return f"Knowledge: {k_total} entries ({k_stats['decision']} decisions, {k_stats['success']} successes, {k_stats['failure']} failures, {k_stats['constraint']} constraints, {k_stats['insight']} insights; {k_stats['superseded']} superseded) | last entry {k_last_date} | {know_path}"
                    
                    know_str = await asyncio.to_thread(_parse_knowledge)

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
                
                async with _MEMORY_MUTEX:
                    async with get_registry_lock():
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

                if config.verbose or not getattr(config, "non_interactive", False):
                    choice = Prompt.ask("Queue these surgical patches into the Task Registry? [Y/N]", choices=["Y", "N"], default="Y")
                else:
                    console.print("[green]Auto-approving surgical patch queue (run interactively to review)[/green]")
                    choice = "Y"
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
                
                async with _MEMORY_MUTEX:
                    async with get_registry_lock():
                        with open("memory.md", "r", encoding="utf-8") as f:
                            fresh_mem = f.read()
                        fresh_mem = re.sub(r"- last_docs_update:.*", f"- last_docs_update: {now_iso}", fresh_mem)
                        with open("memory.md", "w", encoding="utf-8") as f:
                            f.write(fresh_mem)

                console.print("\n[bold green]Tasks successfully queued! Run /dumbledoer:execute to trigger the LLM patch wave.[/bold green]")
                return

            elif command == "start":
                if os.path.exists("memory.md"):
                    print("Error: memory.md already exists. Run /dumbledoer:resume to continue.")
                    return
                    
                print("Bootstrapping native memory.md state machine...")
                from datetime import datetime
                template_path = os.path.join(self.plugin_root, "templates", "memory-template.md")
                
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
                
                self.chat_session = await self.provider.create_chat_session(
                    model_name=self.model, 
                    tools=self._get_tools_for_command(command)
                )
                
                sys_inst = await self._get_system_instructions(command)
                payload = f"{sys_inst}\n\nUSER DIRECTIVE: Execute the `start` command with arguments {args}. Follow your COMMAND SPECIFIC INSTRUCTIONS strictly."
                
                from rich.console import Console
                console = Console()
                with console.status(f"[bold cyan]Running {command} agent...", spinner="dots") as status:
                    try:
                        response = await self._run_with_tools(self.chat_session, payload, self.provider, status=status)
                    except Exception as e:
                        print(f"\n[bold red]Agent execution aborted: {e}[/bold red]")
                        return

                # FIX: Catch Diff-Gate Orphans generated during start
                import glob
                existing_tmps = set(glob.glob(".dumbledoer/tmp/*.tmp"))
                if existing_tmps:
                    print(f"\nFound {len(existing_tmps)} unreviewed files from initialization. Starting review...")
                    await self.batch_diff_review(list(existing_tmps))

                final_text = getattr(response, 'text', '') if hasattr(response, 'text') else str(response)
                print(final_text)

            elif command == "iterate":
                enrich_flag = any(arg.startswith("--enrich") and "true" in arg.lower() for arg in args)
                prompt_text = " ".join([a for a in args if not a.startswith("--enrich")]).strip()
                if len(prompt_text) < 20:
                    print("Error: /dumbledoer iterate requires a detailed prompt (min 20 chars). Vague prompts cause hallucinated task loops.")
                    return
                
                self.chat_session = await self.provider.create_chat_session(
                    model_name=getattr(self, "model", config.model), 
                    tools=self._get_tools_for_command(command)
                )
                
                sys_inst = await self._get_system_instructions(command)
                
                enrich_context = ""
                if enrich_flag and "context7" in self.mcp_sessions:
                    enrich_context = "\n# ENRICHED CONTEXT\n" + await self.mcp_sessions["context7"].call_tool("query-docs", arguments={"query": prompt_text})
                
                payload = f"{sys_inst}\n\nUSER DIRECTIVE: Execute the `iterate` command with the following instruction: {prompt_text}\n{enrich_context}\n\nSTRICT LIMIT: You may call `register_task_batch` at most ONE time, and you may schedule at most 5 tasks total for this iteration."
                from rich.console import Console
                console = Console()
                with console.status(f"[bold cyan]Running {command} agent...", spinner="dots") as status:
                    try:
                        response = await self._run_with_tools(self.chat_session, payload, self.provider, status=status, max_iterations=30)
                    except Exception as e:
                        print(f"\n[bold red]Agent execution aborted: {e}[/bold red]")
                        return
                
                final_text = getattr(response, 'text', '') if hasattr(response, 'text') else str(response)
                print(final_text)

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
                await self._archive_stale_sessions()
            
            # [FIX]: Drain and close all async HTTP client sessions to prevent OS-level file descriptor leaks
            if hasattr(self, "providers"):
                for provider in self.providers.values():
                    if hasattr(provider, "aclose"):
                        await provider.aclose()
                        
            await self.exit_stack.aclose()

    async def _archive_stale_sessions(self):
        archive_keep_sessions = 1
        
        if not os.path.exists("memory.md"):
            return
            
        async with _MEMORY_MUTEX:
            async with get_registry_lock():
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
            async with get_registry_lock():
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
        async with _MEMORY_MUTEX:
            async with get_registry_lock():
                with open(tmp_mem, "w", encoding="utf-8") as f:
                    f.write("\n".join(final_lines))
                os.replace(tmp_mem, "memory.md")
        print(f"Archived {len(to_archive)} session(s) → .dumbledoer/archive/ ({len(lines) - len(final_lines)} lines trimmed from memory.md)")



```

