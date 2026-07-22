import os
import sys
import inspect
import asyncio
from dotenv import load_dotenv
import argparse
import subprocess
import shlex
import re
from contextlib import AsyncExitStack
import shutil
import difflib
from filelock import FileLock

REGISTRY_LOCK = FileLock("memory.md.lock", timeout=10)
# GUI_DIFF_ENABLED will be set dynamically in main_async
from google import genai
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
        self.threshold = 100000
        for line in config_text.splitlines():
            line = line.strip()
            if line.startswith("- budget_limit:"):
                try:
                    self.threshold = int(line.split(":")[1].strip())
                except ValueError:
                    pass
                    
    def check_and_harvest(self):
        if self.estimated_tokens > self.threshold:
            raise BudgetExhaustedException("Budget exhausted")

class ASTMemoryMapper:
    @staticmethod
    def locate_heading_block(content: str, heading_level: str, title: str) -> tuple[int, int]:
        lines = content.splitlines()
        start_idx = -1
        end_idx = -1
        target_pattern = re.compile(rf"^{re.escape(heading_level)}\s+{re.escape(title)}\s*$", re.IGNORECASE)
        for i, line in enumerate(lines):
            if target_pattern.match(line.strip()):
                start_idx = i
                break
        if start_idx != -1:
            end_idx = len(lines)
            in_code_block = False
            for j in range(start_idx + 1, len(lines)):
                stripped = lines[j].strip()
                if stripped.startswith("```"):
                    in_code_block = not in_code_block
                    
                if not in_code_block and re.match(r"^#{1,6}\s+", lines[j]):
                    end_idx = j
                    break
        return start_idx, end_idx

    @staticmethod
    def append_to_markdown_table(file_path: str, header: str, new_row: str) -> None:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        start_idx = -1
        end_idx = -1
        for i in range(1, 7):
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "#" * i, header)
            if start_idx != -1:
                break

        if start_idx != -1:
            lines = content.splitlines()
            last_idx = -1
            for i in range(start_idx + 1, end_idx):
                if lines[i].strip().startswith("|"):
                    last_idx = i

            if last_idx != -1:
                lines.insert(last_idx + 1, new_row)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")

async def execute_bash(command: str, sandbox_mode: str = None) -> str:
    def _read_mode():
        mode = "dumbledoer-base"
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("- sandbox_mode:"):
                        mode = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass
        return mode

    if sandbox_mode is None:
        sandbox_mode = await asyncio.to_thread(_read_mode)

    try:
        if sandbox_mode == "docker-compose":
            args = ["docker", "compose", "exec", "-T", "app", "bash", "-c", command]
        elif sandbox_mode == "native":
            args = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{os.getcwd()}:/workspace", "-w", "/workspace", "target-repo-img", "bash", "-c", command]
        else:
            args = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{os.getcwd()}:/workspace", "-w", "/workspace", "dumbledoer-base:latest", "bash", "-c", command]
            
        result = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error ({e.returncode}):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
    except Exception as e:
        return f"Exception executing command: {e}"

async def read_file(path: str) -> str:
    def _read():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    try:
        return await asyncio.to_thread(_read)
    except Exception as e:
        return f"Error reading file {path}: {e}"

def _write_file(path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {path}"
    except Exception as e:
        return f"Error writing file {path}: {e}"

async def update_memory_registry(target: str, replacement: str) -> str:
    """Updates the memory.md file by performing a synchronous search and replace to prevent concurrency data loss. Pass the EXACT block of text to be replaced as `target`, and the new block of text as `replacement`. This operation happens under a file lock to guarantee atomic modifications."""
    def _do_update():
        with REGISTRY_LOCK:
            try:
                with open("memory.md", "r") as f:
                    current_content = f.read()
                
                if target not in current_content:
                    return f"Error: Target block not found in memory.md. Stale state or invalid target string."
                    
                new_content = current_content.replace(target, replacement, 1)
                
                if "- sandbox_mode:" not in new_content:
                    return "Error updating memory registry: Constraint failed, missing '- sandbox_mode:' in Config block after replacement."
                    
                _write_file("memory.md", new_content)
                return "Successfully updated memory.md via atomic search and replace."
            except Exception as inner_e:
                return f"Inner exception updating memory.md: {inner_e}"
                
    try:
        return await asyncio.to_thread(_do_update)
    except Exception as e:
        return f"Error updating memory registry: {e}"

async def run_rtk(command: str) -> str:
    rtk_bin = shutil.which("rtk")
    if not rtk_bin:
        cargo_path = os.path.expanduser("~/.cargo/bin/rtk")
        if os.path.exists(cargo_path):
            rtk_bin = cargo_path
        elif os.path.exists("./bin/rtk"):
            rtk_bin = "./bin/rtk"
        else:
            return "Error: RTK binary not found in standard paths."

    try:
        args = [rtk_bin] + shlex.split(command)
        result = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error ({e.returncode}):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
    except Exception as e:
        return f"Exception executing rtk command: {e}"

async def write_file_with_review(path: str, content: str) -> str:
    """Writes content to a file via a VS Code Diff-Gate for user approval."""
    try:
        tmp_dir = ".dumbledoer/tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        import uuid
        filename = os.path.basename(path)
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}_{filename}.tmp")
        
        import time
        from datetime import datetime
        manager = CheckpointManager()
        chk_id = f"chk_{int(time.time())}"
        metadata = {
            "Timestamp": datetime.now().isoformat(),
            "Task ID": "manual-edit",
            "Change Summary": f"Update {filename} via Diff-Gate",
            "Rationale": "User-approved manual write_file_with_review",
            "Checkpoint ID": chk_id,
            "Session ID": "manual",
            "Step": "diff-gate",
            "Files Snapshotted": path
        }
        rollback_path = os.path.join(".dumbledoer", "rollbacks", f"{chk_id}_{filename}.bak")
        checkpoint_path = os.path.join(".dumbledoer", "checkpoints", f"{chk_id}.json")
        
        manager.write_rollback_copy(path, rollback_path)
        manager.log_planned_change(path, metadata)
        manager.write_checkpoint_json(checkpoint_path, metadata)
        
        with open(tmp_path, "w") as f:
            f.write(content)
            
        has_code = shutil.which("code") is not None

        if GUI_DIFF_ENABLED and has_code:
            print(f"Review proposed changes for {path} in VS Code.", file=sys.stderr)
            if os.path.exists(path):
                await asyncio.to_thread(subprocess.run, ["code", "--wait", "--diff", path, tmp_path], check=True)
            else:
                await asyncio.to_thread(subprocess.run, ["code", "--wait", tmp_path], check=True)
        else:
            if os.path.exists(path):
                with open(path, "r") as f:
                    old_content = f.readlines()
                new_content = content.splitlines(keepends=True)
                diff = "".join(difflib.unified_diff(old_content, new_content, fromfile=path, tofile=tmp_path))
                if diff:
                    from rich.console import Console
                    from rich.syntax import Syntax
                    console = Console()
                    console.print(Syntax(diff, "diff", theme="monokai"))
            else:
                print(f"Creating new file {path}. Content preview:\n{content}")
            
        from rich.prompt import Confirm
        approval = await asyncio.to_thread(Confirm.ask, f"Approve changes to {path}?")
        if approval:
            os.replace(tmp_path, path)
            return f"Successfully wrote to {path} (Approved by user)"
        else:
            return f"Error: Changes to {path} were rejected by the user."
    except Exception as e:
        return f"Error in write_file_with_review for {path}: {e}"

class CheckpointManager:
    def write_rollback_copy(self, target_path: str, rollback_path: str):
        if os.path.exists(rollback_path):
            return
        if os.path.exists(target_path):
            os.makedirs(os.path.dirname(rollback_path), exist_ok=True)
            shutil.copy2(target_path, rollback_path)
            
    def log_planned_change(self, target_path: str, metadata: dict):
        timestamp = metadata.get("Timestamp", "")
        task_id = metadata.get("Task ID", "")
        summary = metadata.get("Change Summary", "")
        rationale = metadata.get("Rationale", "")
        row = f"| {timestamp} | {task_id} | {target_path} | {summary} | planned | {rationale} |"
        with REGISTRY_LOCK:
            ASTMemoryMapper.append_to_markdown_table("memory.md", "Change Log", row)
        
    def write_checkpoint_json(self, checkpoint_path: str, metadata: dict):
        os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
        with open(checkpoint_path, "w") as f:
            import json
            json.dump(metadata, f, indent=2)
            
        checkpoint_id = metadata.get("Checkpoint ID", "")
        task_id = metadata.get("Task ID", "")
        step = metadata.get("Step", "")
        session_id = metadata.get("Session ID", "")
        files_snapshotted = metadata.get("Files Snapshotted", "")
        row = f"| {checkpoint_id} | {task_id} | {step} | {session_id} | {files_snapshotted} |"
        with REGISTRY_LOCK:
            ASTMemoryMapper.append_to_markdown_table("memory.md", "Checkpoint Registry", row)
            
    def stage_tmp_write(self, tmp_path: str, content: str):
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        with open(tmp_path, "w") as f:
            f.write(content)
            
    def atomic_rename_to_target(self, tmp_path: str, target_path: str):
        os.replace(tmp_path, target_path)
        
    def log_applied_change(self, target_path: str, metadata: dict):
        timestamp = metadata.get("Timestamp", "")
        task_id = metadata.get("Task ID", "")
        summary = metadata.get("Change Summary", "")
        rationale = metadata.get("Rationale", "")
        row = f"| {timestamp} | {task_id} | {target_path} | {summary} | applied | {rationale} |"
        with REGISTRY_LOCK:
            ASTMemoryMapper.append_to_markdown_table("memory.md", "Change Log", row)

class OrphanRecoveryScanner:
    def run(self):
        tmp_dir = ".dumbledoer/tmp"
        chk_dir = ".dumbledoer/checkpoints"
        bak_dir = ".dumbledoer/rollbacks"
        os.makedirs(tmp_dir, exist_ok=True)
        os.makedirs(chk_dir, exist_ok=True)
        os.makedirs(bak_dir, exist_ok=True)
            
        change_log = []
        content = ""
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                content = f.read()
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Change Log")
            if start_idx != -1:
                lines = content.splitlines()[start_idx+1:end_idx]
                for line in lines:
                    if line.strip().startswith("|") and "---" not in line and "Timestamp" not in line:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 7:
                            # | Timestamp | Checkpoint ID | Task ID | Target Path | Action | Status | Rationale |
                            change_log.append({
                                "chk_id": parts[2],
                                "target": parts[4],
                                "status": parts[6],
                                "line_text": line,
                            })
        except FileNotFoundError:
            pass

        import glob
        import filecmp
        from rich.prompt import Confirm
        from rich.console import Console
        console = Console()
        
        valid_chks = {c["chk_id"] for c in change_log}
        planned_chks = {c["chk_id"]: c for c in change_log if c["status"] == "planned"}
        
        # O3: Discard orphaned .json checkpoints
        for chk_file in glob.glob(os.path.join(chk_dir, "*.json")):
            basename = os.path.basename(chk_file)
            chk_id = basename.replace(".json", "")
            if chk_id not in valid_chks:
                os.remove(chk_file)
                console.print(f"[yellow]O3: Discarded orphaned checkpoint {chk_file}[/yellow]")
                
        # O5: Discard orphaned .bak rollbacks
        for bak_file in glob.glob(os.path.join(bak_dir, "*.bak")):
            basename = os.path.basename(bak_file)
            chk_id = basename.split("_")[0] if "_" in basename else basename.replace(".bak", "")
            if chk_id not in valid_chks:
                os.remove(bak_file)
                console.print(f"[yellow]O5: Discarded orphaned rollback {bak_file}[/yellow]")
                
        # O4: Evaluate planned Change Log entries and update memory.md
        new_content = content
        for chk_id, entry in planned_chks.items():
            target = entry["target"]
            bak_files = glob.glob(os.path.join(bak_dir, f"{chk_id}_*.bak"))
            if bak_files and os.path.exists(target):
                bak_file = bak_files[0]
                if filecmp.cmp(target, bak_file, shallow=False):
                    new_status = "rolled-back"
                else:
                    new_status = "applied"
                new_line = entry["line_text"].replace("| planned |", f"| {new_status} |")
                new_content = new_content.replace(entry["line_text"], new_line)
                console.print(f"[green]O4: Resolved planned change {chk_id} as {new_status}[/green]")
        
        if new_content != content:
            with open("memory.md", "w", encoding="utf-8") as f:
                f.write(new_content)
        
        # O1/O2: Handle .tmp files (using basename mapping since UUID is present)
        for file in glob.glob(os.path.join(tmp_dir, "*.tmp")):
            try:
                # Find corresponding target by matching filename ends
                basename = os.path.basename(file)
                actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
                actual_filename = actual_filename.replace(".tmp", "")
                
                matched_target = None
                for c in change_log:
                    if c["status"] == "planned" and os.path.basename(c["target"]) == actual_filename:
                        matched_target = c["target"]
                        break
                        
                if matched_target:
                    if Confirm.ask(f"Found orphaned planned change for [bold]{matched_target}[/bold] (File: {file}). Apply it?"):
                        os.replace(file, matched_target)
                        console.print(f"[green]Applied {file} to {matched_target}[/green]")
                    else:
                        os.remove(file)
                        console.print(f"[yellow]Discarded {file}[/yellow]")
                else:
                    os.remove(file)
            except Exception as e:
                console.print(f"[red]Error recovering {file}: {e}[/red]")

class DumbleDoerCLI:
    def __init__(self):
        self.plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        load_dotenv(dotenv_path=os.path.join(os.getcwd(), '.env'), override=True)
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("Error: GEMINI_API_KEY or GOOGLE_API_KEY not found in environment or local .env file.", file=sys.stderr)
            sys.exit(1)
        self.client = genai.Client(api_key=api_key)
        self.exit_stack = AsyncExitStack()
        self.mcp_sessions = {}
        self.local_tools = [read_file, write_file_with_review, execute_bash, update_memory_registry, run_rtk]
        self.gemini_tools = self.local_tools

    def _create_mcp_wrapper(self, server_name: str, tool):
        async def mcp_wrapper(**kwargs):
            session = self.mcp_sessions[server_name]
            result = await session.call_tool(tool.name, arguments=kwargs)
            return "\n".join([x.text for x in result.content if hasattr(x, 'text')])
        
        safe_name = tool.name.replace("-", "_")
        mcp_wrapper.__name__ = safe_name if safe_name.startswith(server_name) else f"{server_name}_{safe_name}"
        
        # --- DYNAMIC SIGNATURE INJECTION ---
        params = []
        if hasattr(tool, 'inputSchema') and tool.inputSchema and "properties" in tool.inputSchema:
            for prop_name, prop_schema in tool.inputSchema["properties"].items():
                ptype = str
                if prop_schema.get("type") == "integer": ptype = int
                elif prop_schema.get("type") == "boolean": ptype = bool
                elif prop_schema.get("type") == "number": ptype = float
                elif prop_schema.get("type") == "array": ptype = list
                
                is_req = prop_name in tool.inputSchema.get("required", [])
                default = inspect.Parameter.empty if is_req else None
                params.append(inspect.Parameter(
                    name=prop_name, 
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD, 
                    annotation=ptype, 
                    default=default
                ))
        
        mcp_wrapper.__signature__ = inspect.Signature(parameters=params)
        mcp_wrapper.__doc__ = getattr(tool, 'description', '')
        return mcp_wrapper

    async def connect_mcp(self):
        # Connect to codegraph
        codegraph_params = StdioServerParameters(
            command="npx",
            args=["-y", "--package=@colbymchenry/codegraph", "codegraph", "serve", "--mcp"]
        )
        codegraph_transport, codegraph_stream = await self.exit_stack.enter_async_context(stdio_client(codegraph_params))
        codegraph_session = await self.exit_stack.enter_async_context(ClientSession(codegraph_transport, codegraph_stream))
        await codegraph_session.initialize()
        cg_tools = await codegraph_session.list_tools()
        for tool in cg_tools.tools:
            self.gemini_tools.append(self._create_mcp_wrapper("codegraph", tool))
        self.mcp_sessions["codegraph"] = codegraph_session

        # Connect to context7
        context7_params = StdioServerParameters(
            command="npx",
            args=["--yes", "--quiet", "@upstash/context7-mcp"]
        )
        context7_transport, context7_stream = await self.exit_stack.enter_async_context(stdio_client(context7_params))
        context7_session = await self.exit_stack.enter_async_context(ClientSession(context7_transport, context7_stream))
        await context7_session.initialize()
        c7_tools = await context7_session.list_tools()
        for tool in c7_tools.tools:
            self.gemini_tools.append(self._create_mcp_wrapper("context7", tool))
        self.mcp_sessions["context7"] = context7_session

    async def _graceful_shutdown(self, task_id: str = None):
        print("CRITICAL: Budget Exhausted. Initiating Graceful Shutdown Sequence...")
        def _shutdown():
            with REGISTRY_LOCK:
                try:
                    with open("memory.md", "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    if task_id:
                        content = content.replace(f"| {task_id} | in-progress", f"| {task_id} | interrupted")
                    
                    summary = f"\n\n## Session Handoff Summary\n- Outcome: interrupted-budget\n"
                    if task_id:
                        summary += f"- Interrupted Task: {task_id}\n"
                    summary += "- Recommended Next Scope: Resume interrupted tasks\n"
                    
                    if "## Session Handoff Summary" not in content:
                        content += summary
                        
                    with open("memory.md", "w", encoding="utf-8") as f:
                        f.write(content)
                except Exception as e:
                    print(f"Error during graceful shutdown: {e}")
                    
        await asyncio.to_thread(_shutdown)
        print("Graceful Shutdown Sequence Complete. State preserved in memory.md.")

    async def _get_system_instructions(self):
        instructions = [
            "# MISSION",
            "You are DumbleDoer, an Agent Engineering Harness. Your goal is to systematically analyze, improve, and validate agent projects.",
            await self.local_tools[0](os.path.join(self.plugin_root, "SYSTEM_INSTRUCTIONS.md")) or "Core rules not found.",
            await self.local_tools[0](os.path.join(self.plugin_root, "lib", "common-preamble.md")) or "",
            await self.local_tools[0](os.path.join(self.plugin_root, "lib", "compression-policy.md")) or "",
            await self.local_tools[0]("memory.md") or "No memory.md found. Start a new project."
        ]
        return "\n\n".join(instructions)

    async def execute_task(self, task_id: str, description: str):
        print(f"Executing task {task_id}: {description}")
        chat_session = self.client.aio.chats.create(model="gemini-2.5-flash", config={"tools": self.gemini_tools})
        system_instructions = await self._get_system_instructions()
        prompt_payload = f"""{system_instructions}

This project has CodeGraph initialized (.codegraph/ exists). You are executing task {task_id}: {description}.

Mandatory rules:
1. Read {os.path.join(self.plugin_root, 'lib', 'codegraph-integration.md')} before modifying any file.
2. Follow the 10-step data flow for change tasks exactly.
3. Follow {os.path.join(self.plugin_root, 'lib', 'checkpoint-protocol.md')} for every file write.
4. Log your codegraph_impact result to memory.md task {task_id} CodeGraph Impact field.
5. Do not modify any file listed in another in-progress task's Outputs."""
        try:
            response = await chat_session.send_message(prompt_payload)
            print(f"Task {task_id} completed: {response.text}")
        except BudgetExhaustedException:
            await self._graceful_shutdown(task_id)

    def get_pending_waves(self) -> list[list[dict]]:
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return []
            
        start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Task Registry")
        if start_idx == -1:
            return []
            
        lines = content.splitlines()[start_idx+1:end_idx]
        
        tasks = []
        for line in lines:
            if not line.strip().startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 9 and parts[1] != "Task ID" and not parts[1].startswith("---"):
                task_id = parts[1]
                title = parts[2]
                status = parts[4]
                depends_on = parts[6]
                
                desc_start, desc_end = ASTMemoryMapper.locate_heading_block(content, "###", task_id)
                description = title
                if desc_start != -1:
                    desc_lines = content.splitlines()[desc_start+1:desc_end]
                    for dline in desc_lines:
                        if dline.startswith("- **Description**:"):
                            description = dline.split("- **Description**:")[1].strip()
                            break

                tasks.append({
                    "id": task_id,
                    "desc": description,
                    "status": status,
                    "deps": [d.strip() for d in depends_on.split(",")] if depends_on != "none" else []
                })

        pending_tasks = {t['id']: t for t in tasks if t['status'] == 'pending'}
        completed_task_ids = {t['id'] for t in tasks if t['status'] == 'completed'}
        
        waves = []
        while pending_tasks:
            current_wave = []
            for t_id, t in list(pending_tasks.items()):
                if all(d in completed_task_ids for d in t['deps']):
                    current_wave.append(t)
            
            if not current_wave:
                if pending_tasks:
                    blocked = []
                    for t_id, t in pending_tasks.items():
                        unfulfilled = [d for d in t['deps'] if d not in completed_task_ids]
                        blocked.append(f"{t_id} (missing: {', '.join(unfulfilled)})")
                    raise DependencyGraphError(f"Dependency graph cannot resolve. Blocked tasks: {'; '.join(blocked)}")
                break
                
            waves.append(current_wave)
            for t in current_wave:
                del pending_tasks[t['id']]
                completed_task_ids.add(t['id'])
                
        return waves

    async def run(self, command: str, args: list):
        print(f"DumbleDoer running command: {command}")
        if command == "resume":
            OrphanRecoveryScanner().run()
            # we can fall through to normal execution if it resumes agent logic, or just run the scanner
        await self.connect_mcp()
        try:
            if command == "execute":
                waves = self.get_pending_waves()
                if not waves:
                    print("No pending tasks to execute.")
                for i, wave in enumerate(waves):
                    print(f"Starting execution wave {i+1} with {len(wave)} tasks...")
                    try:
                        await asyncio.gather(*[self.execute_task(t['id'], t['desc']) for t in wave])
                    except BudgetExhaustedException:
                        await self._graceful_shutdown()
                        break
            else:
                self.chat_session = self.client.aio.chats.create(model="gemini-2.5-flash", config={"tools": self.gemini_tools})
                response = await self.chat_session.send_message(f"Execute {command} with {args}")
                print(response.text)
        finally:
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
        
        for idx, line in enumerate(lines):
            if re.match(r"^###\s+(T-\d+)", line):
                if current_task:
                    tasks[current_task] = current_lines
                current_task = re.match(r"^###\s+(T-\d+)", line).group(1)
                current_lines = [line]
            elif current_task:
                if re.match(r"^#+\s+", line):
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
        with open(tmp_mem, "w", encoding="utf-8") as f:
            f.write("\n".join(final_lines))
        os.replace(tmp_mem, "memory.md")
        print(f"Archived {len(to_archive)} session(s) → .dumbledoer/archive/ ({len(lines) - len(final_lines)} lines trimmed from memory.md)")


async def main_async():
    parser = argparse.ArgumentParser(description="DumbleDoer CLI")
    parser.add_argument(
        "command",
        choices=["start", "execute", "resume", "report", "rollback", "update-docs", "audit", "iterate", "status"],
        help="The dumbledoer command to run"
    )
    parser.add_argument("--no-gui", action="store_true", help="Disable GUI diff-gate for headless environments")
    args, unknown = parser.parse_known_args()
    
    global GUI_DIFF_ENABLED
    GUI_DIFF_ENABLED = not args.no_gui
    
    if GUI_DIFF_ENABLED:
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                content = f.read()
            start, end = ASTMemoryMapper.locate_heading_block(content, "##", "Config")
            if start != -1:
                config_lines = content.splitlines()[start:end]
                if any("gui_diff_enabled: false" in line.lower() for line in config_lines):
                    GUI_DIFF_ENABLED = False
        except FileNotFoundError:
            pass
    
    cli = DumbleDoerCLI()
    await cli.run(args.command, unknown)

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
