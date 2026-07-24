import sys
import sys
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
import filelock

_REGISTRY_LOCK = __import__('threading').RLock()
def get_registry_lock():
    return _REGISTRY_LOCK
# GUI_DIFF_ENABLED will be set dynamically in main_async
GUI_DIFF_ENABLED = True
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
        self.budget_limit = 100000
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
        self.estimated_tokens += count
        
    def check_and_harvest(self):
        if self.estimated_tokens >= self.shutdown_threshold:
            raise BudgetExhaustedException(f"Budget exhausted: {self.estimated_tokens} >= {self.shutdown_threshold}")

class ASTMemoryMapper:
    @staticmethod
    def locate_heading_block(content: str, heading_level: str, title: str) -> tuple[int, int]:
        lines = content.splitlines()
        start_idx = -1
        end_idx = -1
        target_pattern = re.compile(rf"^{re.escape(heading_level)}\s+{re.escape(title)}\s*$", re.IGNORECASE)
        in_code_block = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
            if not in_code_block and target_pattern.match(stripped):
                start_idx = i
                break
                
        if start_idx != -1:
            end_idx = len(lines)
            in_code_block = False
            for j in range(start_idx + 1, len(lines)):
                stripped = lines[j].strip()
                if stripped.startswith("```"):
                    in_code_block = not in_code_block
                if not in_code_block and re.match(r"^#{1,6}\s+", stripped):
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
            with get_registry_lock():
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
        import platform
        user_args = [] if platform.system() == "Windows" else ["--user", f"{os.getuid()}:{os.getgid()}"]
        
        if sandbox_mode == "native":
            args = ["bash", "-c", command]
        elif sandbox_mode.startswith("compose:") or sandbox_mode == "compose":
            service_name = None
            if ":" in sandbox_mode:
                service_name = sandbox_mode.split(":", 1)[1].strip()
            
            # Find compose file
            compose_file = None
            for f in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
                if os.path.exists(f):
                    compose_file = f
                    break
                    
            if not compose_file:
                return "Error: sandbox_mode is compose but no docker-compose.yml found in repository."
                
            if not service_name:
                import re
                try:
                    with open(compose_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    match = re.search(r'^services:\s*\n\s+([a-zA-Z0-9_-]+):', content, re.MULTILINE)
                    if match:
                        service_name = match.group(1)
                    else:
                        return f"Error: Could not automatically detect a service in {compose_file}. Specify it explicitly via `sandbox_mode: compose:<service>`"
                except Exception as e:
                    return f"Error reading compose file: {e}"
            
            args = ["docker", "compose", "-f", compose_file, "run", "--rm", service_name, "bash", "-c", command]
            
        elif sandbox_mode.startswith("docker:"):
            image_name = sandbox_mode.split(":", 1)[1].strip()
            args = ["docker", "run", "--rm"] + user_args + [
                "-v", f"{os.getcwd()}:/workspace", "-w", "/workspace", 
                image_name, "bash", "-c", command
            ]
        else:
            args = ["docker", "run", "--rm"] + user_args + [
                "-v", f"{os.getcwd()}:/workspace", "-w", "/workspace", 
                "dumbledoer-base:latest", "bash", "-c", command
            ]
            
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
    """Updates the memory.md file securely with exponential backoff on lock timeouts."""
    def _do_update():
        with FileLock("memory.md.lock", timeout=60):
            with open("memory.md", "r", encoding="utf-8") as f:
                current_content = f.read()
            
            if target not in current_content:
                return "Error: Target block not found in memory.md. Stale state or invalid target string."
                
            new_content = current_content.replace(target, replacement, 1)
            
            if "- sandbox_mode:" not in new_content:
                return "Error updating memory registry: Constraint failed, missing '- sandbox_mode:' in Config block after replacement."
                
            os.makedirs(os.path.dirname(os.path.abspath("memory.md")), exist_ok=True)
            with open("memory.md", "w", encoding="utf-8") as f:
                f.write(new_content)
            return "Successfully updated memory.md via atomic search and replace."

    for attempt in range(5):
        try:
            return await asyncio.to_thread(_do_update)
        except filelock.Timeout:
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            return f"Error updating memory registry: {e}"
            
    return "Error: Failed to acquire memory.md.lock after 5 attempts due to high concurrency load."

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

class TaskRegistryState:
    def __init__(self):
        self.json_path = ".dumbledoer/task_registry.json"
        self.md_path = "memory.md"
        os.makedirs(os.path.dirname(self.json_path), exist_ok=True)
        
    def load_tasks(self) -> dict:
        with get_registry_lock():
            tasks = {}
            try:
                with open(self.md_path, "r", encoding="utf-8") as f:
                    content = f.read()
                start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Task Registry")
                if start_idx != -1:
                    lines = content.splitlines()[start_idx+1:end_idx]
                    for line in lines:
                        parts = [p.strip() for p in line.split("|")]

                        header_line = next((l for l in content.splitlines()[start_idx:end_idx] if "Task ID" in l), None)
                        if header_line:
                            headers = [h.strip() for h in header_line.split("|") if h.strip()]
                            id_idx = headers.index("Task ID") + 1 if "Task ID" in headers else 1
                            stat_idx = headers.index("Status") + 1 if "Status" in headers else 4
                            title_idx = headers.index("Title") + 1 if "Title" in headers else 2
                            dep_idx = headers.index("Depends On") + 1 if "Depends On" in headers else 6
                        else:
                            id_idx, stat_idx, title_idx, dep_idx = 1, 4, 2, 6

                        if len(parts) > max(id_idx, stat_idx) and "Task ID" not in parts[id_idx] and not parts[id_idx].strip().startswith("---"):
                            task_id = parts[id_idx].strip()
                            
                            desc_start, desc_end = ASTMemoryMapper.locate_heading_block(content, "###", task_id)
                            description = parts[title_idx].strip() if len(parts) > title_idx else ""
                            target_files = []
                            
                            if desc_start != -1:
                                desc_lines = content.splitlines()[desc_start+1:desc_end]
                                for dline in desc_lines:
                                    if dline.startswith("- **Description**:"):
                                        description = dline.split("- **Description**:")[1].strip()
                                    if dline.startswith("- **Outputs**:"):
                                        raw_outputs = dline.split("- **Outputs**:")[1].strip()
                                        if raw_outputs.lower() not in ["none", "—", "-", ""]:
                                            target_files = [f.strip() for f in raw_outputs.replace("[", "").replace("]", "").split(",")]
                                        
                            status_col = parts[stat_idx].strip() if len(parts) > stat_idx else "pending"
                            
                            deps_str = ""
                            for p in parts:
                                if "T-" in p and p.strip() != task_id:
                                    deps_str += p + ","
                            deps = [d.strip() for d in deps_str.split(",") if "T-" in d]

                            tasks[task_id] = {
                                "id": task_id,
                                "desc": description,
                                "title": parts[title_idx].strip() if len(parts) > title_idx else task_id,
                                "status": status_col,
                                "deps": deps,
                                "outputs": target_files,
                                "original_line": line
                            }
            except Exception:
                pass
            self.save_tasks(tasks)
            return tasks

    def save_tasks(self, tasks: dict):
        self._sync_to_markdown(tasks)
        
    async def update_task_status(self, task_id: str, new_status: str):
        def _do_update():
            with get_registry_lock():
                tasks = self.load_tasks()
                if task_id in tasks:
                    tasks[task_id]["status"] = new_status
                    self.save_tasks(tasks)
        await asyncio.to_thread(_do_update)

    def _sync_to_markdown(self, tasks: dict):
        with get_registry_lock():
            try:
                with open(self.md_path, "r", encoding="utf-8") as f:
                    content = f.read()
                start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Task Registry")
                if start_idx == -1: return
                
                lines = content.splitlines()
                new_block = []
                for line in lines[start_idx+1:end_idx]:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 5 and "Task ID" not in parts[1] and not parts[1].strip().startswith("---"):
                        tid = parts[1].strip()
                        if tid in tasks:
                            stat_idx = next((i for i, h in enumerate([h.strip() for h in content.splitlines()[start_idx].split("|") if h.strip()]) if h == "Status"), 3) + 1
                            if len(parts) > stat_idx:
                                parts[stat_idx] = f" {tasks[tid]['status']} "
                            else:
                                parts[4] = f" {tasks[tid]['status']} "
                            new_block.append("|".join(parts))
                        else:
                            new_block.append(line)
                    else:
                        new_block.append(line)
                            
                new_content = "\n".join(lines[:start_idx+1] + new_block + lines[end_idx:])
                with open(self.md_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
            except Exception:
                pass

async def write_file_with_review(path: str, content: str) -> str:
    """Writes content to a file via a VS Code Diff-Gate for user approval."""
    try:
        try:
            import subprocess
            impact_proc = await asyncio.to_thread(
                subprocess.run, 
                ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "impact", path], 
                capture_output=True, text=True
            )
            import re
            match = re.search(r"—\s*(\d+)\s+affected symbol", impact_proc.stdout if hasattr(impact_proc, 'stdout') else str(impact_proc))
            if match and int(match.group(1)) > 20:
                return f"Error: CodeGraph impact threshold exceeded ({match.group(1)} symbols > 20). Write blocked to prevent system instability."
        except Exception as e:
            pass

        tmp_dir = ".dumbledoer/tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        import uuid
        encoded_path = path.replace("/", "__")
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}_{encoded_path}.tmp")
        
        import time
        from datetime import datetime
        manager = CheckpointManager()
        chk_id = f"chk_{int(time.time())}"
        metadata = {
            "Timestamp": datetime.now().isoformat(),
            "Task ID": "manual-edit",
            "Change Summary": f"Update {os.path.basename(path)} via Diff-Gate",
            "Rationale": "User-approved manual write_file_with_review",
            "Checkpoint ID": chk_id,
            "Session ID": "manual",
            "Step": "diff-gate",
            "Files Snapshotted": path
        }
        rollback_path = os.path.join(".dumbledoer", "rollbacks", f"{chk_id}_{encoded_path}.bak")
        checkpoint_path = os.path.join(".dumbledoer", "checkpoints", f"{chk_id}.json")
        
        await manager.write_rollback_copy(path, rollback_path)
        await manager.log_planned_change(path, metadata)
        await manager.write_checkpoint_json(checkpoint_path, metadata)
        
        with open(tmp_path, "w") as f:
            f.write(content)
            
        return f"Successfully staged changes for {path} (Pending wave review)"
    except Exception as e:
        return f"Error in write_file_with_review for {path}: {e}"

class CheckpointManager:
    async def write_rollback_copy(self, target_path: str, rollback_path: str):
        def _do_write():
            if os.path.exists(rollback_path):
                return
            if os.path.exists(target_path):
                os.makedirs(os.path.dirname(rollback_path), exist_ok=True)
                shutil.copy2(target_path, rollback_path)
        await asyncio.to_thread(_do_write)
            
    async def log_planned_change(self, target_path: str, metadata: dict):
        timestamp = metadata.get("Timestamp", "")
        task_id = metadata.get("Task ID", "")
        summary = metadata.get("Change Summary", "")
        rationale = metadata.get("Rationale", "")
        row = f"| {timestamp} | {task_id} | {target_path} | {summary} | planned | {rationale} |"
        def _do_log():
            with get_registry_lock():
                ASTMemoryMapper.append_to_markdown_table("memory.md", "Change Log", row)
        await asyncio.to_thread(_do_log)
        
    async def write_checkpoint_json(self, checkpoint_path: str, metadata: dict):
        def _do_write():
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
            with get_registry_lock():
                ASTMemoryMapper.append_to_markdown_table("memory.md", "Checkpoint Registry", row)
        await asyncio.to_thread(_do_write)
            
    async def stage_tmp_write(self, tmp_path: str, content: str):
        def _do_write():
            os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
            with open(tmp_path, "w") as f:
                f.write(content)
        await asyncio.to_thread(_do_write)
            
    async def atomic_rename_to_target(self, tmp_path: str, target_path: str):
        def _do_rename():
            os.replace(tmp_path, target_path)
        await asyncio.to_thread(_do_rename)
        
    async def log_applied_change(self, target_path: str, metadata: dict):
        timestamp = metadata.get("Timestamp", "")
        task_id = metadata.get("Task ID", "")
        summary = metadata.get("Change Summary", "")
        rationale = metadata.get("Rationale", "")
        row = f"| {timestamp} | {task_id} | {target_path} | {summary} | applied | {rationale} |"
        def _do_log():
            with get_registry_lock():
                ASTMemoryMapper.append_to_markdown_table("memory.md", "Change Log", row)
        await asyncio.to_thread(_do_log)

class OrphanRecoveryScanner:
    def run(self):
        with get_registry_lock():
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
            
            # O1/O2: Handle .tmp files
            for file in glob.glob(os.path.join(tmp_dir, "*.tmp")):
                try:
                    # Find corresponding target by decoding the path
                    basename = os.path.basename(file)
                    actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
                    actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")
                    
                    matched_target = None
                    for c in change_log:
                        if c["status"] == "planned" and c["target"] == actual_filename:
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


async def add_task(task_id: str, title: str, task_type: str = "change", deps: str = "none", description: str = "", outputs: str = "none") -> str:
    """Registers a new atomic task to the memory.md Task Registry and Task Details."""
    def _write():
        with get_registry_lock():
            try:
                # 1. Append to Task Registry
                row = f"| {task_id} | {title} | {task_type} | pending | — | {deps} | — | none |"
                ASTMemoryMapper.append_to_markdown_table("memory.md", "Task Registry", row)
                
                # 2. Append to Task Details
                with open("memory.md", "r", encoding="utf-8") as f:
                    content = f.read()
                
                details = f"\n### {task_id}: {title}\n- **Type**: {task_type}\n- **Status**: pending\n- **Owner**: —\n- **Depends On**: {deps}\n- **Assigned Session**: —\n- **Description**: {description}\n- **Inputs**: none\n- **Outputs**: {outputs}\n- **Success Criteria**: TBD\n- **Estimated Effort**: small\n- **Parallelizable**: yes\n- **CodeGraph Impact**: —\n- **Checkpoint**: none\n- **Resume Instructions**: none\n- **Notes**: —\n"
                
                start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Task Details")
                if start_idx != -1:
                    lines = content.splitlines()
                    lines.insert(end_idx, details)
                    with open("memory.md", "w", encoding="utf-8") as f:
                        f.write("\n".join(lines) + "\n")
                return f"Successfully registered task {task_id}."
            except Exception as e:
                return f"Error adding task: {e}"
    return await asyncio.to_thread(_write)

class DumbleDoerCLI:
    def __init__(self):
        self.plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        load_dotenv(dotenv_path=os.path.join(os.getcwd(), '.env'), override=False)
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("Error: GEMINI_API_KEY or GOOGLE_API_KEY not found in environment or local .env file.", file=sys.stderr)
            sys.exit(1)
        self.client = genai.Client(api_key=api_key)
        self.exit_stack = AsyncExitStack()
        self.mcp_sessions = {}
        self.mcp_locks = {}
        self.local_tools = [read_file, write_file_with_review, execute_bash, update_memory_registry, run_rtk, add_task]
        self.gemini_tools = list(self.local_tools)
        
        # Initialize BudgetManager
        try:
            with get_registry_lock():
                with open("memory.md", "r", encoding="utf-8") as f:
                    self.budget_manager = BudgetManager(f.read())
        except Exception:
            self.budget_manager = BudgetManager("")

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
            if len(tools_to_add) > 50:
                print(f"Warning: codegraph MCP provided {len(tools_to_add)} tools. Truncating to 50 to prevent context bloat.", file=sys.stderr)
                tools_to_add = tools_to_add[:50]
                
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
            if len(tools_to_add) > 50:
                print(f"Warning: context7 MCP provided {len(tools_to_add)} tools. Truncating to 50 to prevent context bloat.", file=sys.stderr)
                tools_to_add = tools_to_add[:50]
                
            for tool in tools_to_add:
                self.gemini_tools.append(self._create_mcp_wrapper("context7", tool))
            self.mcp_sessions["context7"] = context7_session
        except Exception as e:
            import sys
            print(f"Context7 MCP degraded: {e}", file=sys.stderr)

        # --- DYNAMIC FALLBACK INJECTION ---
        # Prevent SDK KeyErrors if MCP servers degrade and drop critical tools
        existing_tools = [getattr(t, "__name__", "") for t in self.gemini_tools]
        
        for missing_tool in ["codegraph_impact", "codegraph_search", "codegraph_callers", "codegraph_affected", "codegraph_context", "codegraph_node"]:
            if missing_tool not in existing_tools:
                # Late binding requires a factory to capture the name correctly in the closure
                def create_dummy(name):
                    async def dummy_fallback(query: str = "", target: str = "", symbol: str = "", depth: int = 3, **kwargs) -> str:
                        raise RuntimeError(f"[{name} Degraded] Tool not available from MCP server. Hard aborting to prevent hallucination.")
                    dummy_fallback.__name__ = name
                    dummy_fallback.__qualname__ = name
                    dummy_fallback.__doc__ = f"Fallback dummy for {name}."
                    return dummy_fallback
                
                self.gemini_tools.append(create_dummy(missing_tool))

    async def _graceful_shutdown(self, task_id: str = None):
        print("CRITICAL: Budget Exhausted. Initiating Graceful Shutdown Sequence...")
        def _shutdown():
            with get_registry_lock():
                with open("memory.md", "r", encoding="utf-8") as f:
                    content = f.read()
                
                if task_id:
                    content = content.replace(f"| {task_id} | in_progress", f"| {task_id} | interrupted")
                
                summary = f"## Session Handoff Summary\n- Outcome: interrupted-budget\n"
                if task_id:
                    summary += f"- Interrupted Task: {task_id}\n"
                summary += "- Recommended Next Scope: Resume interrupted tasks\n"
                
                start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Session Handoff Summary")
                if start_idx != -1:
                    lines = content.splitlines()
                    content = "\n".join(lines[:start_idx] + [summary.strip()] + lines[end_idx:])
                else:
                    content += f"\n\n{summary}"
                    
                with open("memory.md", "w", encoding="utf-8") as f:
                    f.write(content)
                    
        await asyncio.to_thread(_shutdown)
        print("Graceful Shutdown Sequence Complete. State preserved in memory.md.")

    async def _get_system_instructions(self, command: str = None):
        instructions = [
            "# MISSION",
            "You are DumbleDoer, an Agent Engineering Harness. Your goal is to systematically analyze, improve, and validate agent projects.",
            await self.local_tools[0](os.path.join(self.plugin_root, "SYSTEM_INSTRUCTIONS.md")) or "Core rules not found.",
            await self.local_tools[0](os.path.join(self.plugin_root, "lib", "common-preamble.md")) or "",
            await self.local_tools[0](os.path.join(self.plugin_root, "lib", "compression-policy.md")) or "",
            await self.local_tools[0]("memory.md") or "No memory.md found. Start a new project."
        ]
        if command and command != "execute":
            skill_path = os.path.join(self.plugin_root, "skills", command, "INSTRUCTIONS.md")
            skill_content = await self.local_tools[0](skill_path)
            if skill_content and not skill_content.startswith("Error"):
                instructions.append(f"# COMMAND SPECIFIC INSTRUCTIONS ({command})\n{skill_content}")
        return "\n\n".join(instructions)



    async def _run_with_tools(self, chat_session, initial_payload):
        response = await chat_session.send_message(initial_payload)
        while response.function_calls:
            from google.genai.types import Part
            parts = []
            for call in response.function_calls:
                tool_name = call.name
                tool_func = None
                for t in self.gemini_tools:
                    if getattr(t, "__name__", "") == tool_name:
                        tool_func = t
                        break
                
                if tool_func:
                    try:
                        args = dict(call.args) if call.args else {}
                        print(f"Executing tool: {tool_name}")
                        import asyncio
                        if asyncio.iscoroutinefunction(tool_func):
                            result = await tool_func(**args)
                        else:
                            result = tool_func(**args)
                        parts.append(Part.from_function_response(
                            name=tool_name,
                            response={"result": str(result)}
                        ))
                    except Exception as e:
                        print(f"Tool {tool_name} failed: {e}")
                        parts.append(Part.from_function_response(
                            name=tool_name,
                            response={"error": str(e)}
                        ))
                else:
                    print(f"Tool {tool_name} not found")
                    parts.append(Part.from_function_response(
                        name=tool_name,
                        response={"error": "Tool not found"}
                    ))
            response = await chat_session.send_message(parts)
        return response

    async def execute_task(self, task_id: str, description: str):
        print(f"Executing task {task_id}: {description}")
        chat_session = self.client.aio.chats.create(model=getattr(self, "model", "gemini-3.6-flash"), config={"tools": list(self.gemini_tools), "automatic_function_calling": {"disable": True}})
        system_instructions = await self._get_system_instructions()
        prompt_payload = f"""{system_instructions}

This project has CodeGraph initialized (.codegraph/ exists). You are executing task {task_id}: {description}.

Mandatory rules:
1. Read {os.path.join(self.plugin_root, 'lib', 'codegraph-integration.md')} before modifying any file.
2. Follow the 10-step data flow for change tasks exactly.
3. Follow {os.path.join(self.plugin_root, 'lib', 'checkpoint-protocol.md')} for every file write.
4. Log your codegraph_impact result to memory.md task {task_id} CodeGraph Impact field.
5. Do not modify any file listed in another in_progress task's Outputs."""
        try:
            response = await self._run_with_tools(chat_session, prompt_payload)
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                self.budget_manager.add_tokens(getattr(response.usage_metadata, 'total_token_count', 0))
            self.budget_manager.check_and_harvest()
            print(f"Task {task_id} completed: {response.text}")
            await TaskRegistryState().update_task_status(task_id, "awaiting-review")
        except BudgetExhaustedException:
            try:
                rtk_out = await run_rtk("gain")
                response = await self._run_with_tools(chat_session, prompt_payload)
                print(f"Task {task_id} completed: {response.text}")
                await TaskRegistryState().update_task_status(task_id, "awaiting-review")
            except (BudgetExhaustedException, RuntimeError) as e:
                print(f"Task failed or budget threshold blocked retry: {e}")
                await self._graceful_shutdown(task_id)

    def get_pending_waves(self) -> list[list[dict]]:
        state = TaskRegistryState()
        tasks_dict = state.load_tasks()
        tasks = list(tasks_dict.values())
        
        pending_tasks = {t['id']: t for t in tasks if "pending" in t['status']}
        completed_task_ids = {t['id'] for t in tasks if "completed" in t['status']}
        
        waves = []
        while pending_tasks:
            current_wave = []
            claimed_files_in_wave = set()
            
            for t_id, t in list(pending_tasks.items()):
                if all(d in completed_task_ids for d in t['deps']):
                    task_files = set(t.get('outputs', []))
                    if not task_files or not task_files.intersection(claimed_files_in_wave):
                        current_wave.append(t)
                        claimed_files_in_wave.update(task_files)
            
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
        
    async def batch_diff_review(self, wave_tmp_files: list):
        if not wave_tmp_files: return
        import subprocess, shutil, sys, os
        has_code = shutil.which("code") is not None
        if GUI_DIFF_ENABLED and has_code:
            print("Review proposed changes for the wave in VS Code.", file=sys.stderr)
            args = ["code", "--wait"] + wave_tmp_files
            await asyncio.to_thread(subprocess.run, args, check=False)
        else:
            import difflib
            from rich.syntax import Syntax
            from rich.console import Console
            console_diff = Console()
            for tmp_path in wave_tmp_files:
                basename = os.path.basename(tmp_path)
                actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
                actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")
                
                original_text = ""
                if os.path.exists(actual_filename):
                    with open(actual_filename, "r") as f:
                        original_text = f.read()
                        
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
        choice = Prompt.ask("Approve wave changes? [Y(all)/N(none)/S(select)]", choices=["Y", "N", "S"], default="Y")
        rejected_files = set()
        if choice == "S":
            sel = Prompt.ask("Enter filenames to reject (comma separated)")
            rejected_files = {s.strip() for s in sel.split(",") if s.strip()}
        elif choice == "N":
            rejected_files = {os.path.basename(f) for f in wave_tmp_files}
            
        state = TaskRegistryState()
        for tmp_path in wave_tmp_files:
            basename = os.path.basename(tmp_path)
            actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
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
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                console.print(f"[yellow]Rejected changes for {actual_filename}[/yellow]")
                if task_id:
                    await state.update_task_status(task_id, "pending")
            else:
                if os.path.exists(tmp_path):
                    os.replace(tmp_path, target_path)
                console.print(f"[green]Approved changes for {actual_filename}[/green]")
                if task_id:
                    await state.update_task_status(task_id, "completed")

        if rejected_files:
            await asyncio.to_thread(OrphanRecoveryScanner().run)

    async def run(self, command: str, args: list, model: str = "gemini-3.6-flash"):
        self.model = model
        print(f"DumbleDoer running command: {command}")
        if command == "resume":
            OrphanRecoveryScanner().run()
            # we can fall through to normal execution if it resumes agent logic, or just run the scanner
        await self.connect_mcp()
        try:
            if command == "rollback":
                if not args:
                    print("Error: must provide a task ID (e.g., T-001)")
                    return
                task_id = args[0]
                bak_dir = f".dumbledoer/rollbacks/{task_id}"
                if not os.path.exists(bak_dir):
                    print(f"Error: No rollbacks found for {task_id}")
                    return
                for root, _, files in os.walk(bak_dir):
                    for file in files:
                        bak_path = os.path.join(root, file)
                        rel_path = bak_path.replace(bak_dir + "/", "").replace("__colon__", ":").replace("__", "/")
                        os.replace(bak_path, rel_path)
                        print(f"Restored {rel_path}")
                await TaskRegistryState().update_task_status(task_id, "pending")
                print(f"Task {task_id} rolled back to pending.")
                return
    
            if command == "execute":
                waves = self.get_pending_waves()
                if not waves:
                    print("No pending tasks to execute.")
                for i, wave in enumerate(waves):
                    print(f"Starting execution wave {i+1} with {len(wave)} tasks...")
                    import glob
                    before_tmps = set(glob.glob(".dumbledoer/tmp/*.tmp"))
                    try:
                        await asyncio.gather(*[self.execute_task(t['id'], t['desc']) for t in wave])
                    except BudgetExhaustedException:
                        await self._graceful_shutdown()
                        break
                    after_tmps = set(glob.glob(".dumbledoer/tmp/*.tmp"))
                    wave_tmps = list(after_tmps - before_tmps)
                    if wave_tmps:
                        await self.batch_diff_review(wave_tmps)
            else:
                self.chat_session = self.client.aio.chats.create(model=getattr(self, "model", "gemini-3.6-flash"), config={"tools": list(self.gemini_tools), "automatic_function_calling": {"disable": True}})
                sys_inst = await self._get_system_instructions(command)
                payload = f"{sys_inst}\n\nUSER DIRECTIVE: Execute the `{command}` command with arguments {args}. Follow your COMMAND SPECIFIC INSTRUCTIONS strictly. Do not ask for user input if a tool can accomplish the task."
                response = await self._run_with_tools(self.chat_session, payload)
                if response.function_calls:
                    print("Function Calls that were not handled:", response.function_calls)
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


async def main_async():
    parser = argparse.ArgumentParser(description="DumbleDoer CLI")
    parser.add_argument(
        "command",
        choices=["start", "execute", "resume", "report", "rollback", "update-docs", "audit", "iterate", "status"],
        help="The dumbledoer command to run"
    )
    parser.add_argument("--model", default=os.getenv("AGY_MODEL", "gemini-3.6-flash"), help="Model override")
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
    await cli.run(args.command, unknown, model=args.model)

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()