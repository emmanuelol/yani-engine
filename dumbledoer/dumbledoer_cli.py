import os
import shutil
import sys
from filelock import FileLock
import asyncio
import subprocess
import shlex
from typing import List, Optional, Dict
from dotenv import load_dotenv
from google import genai
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.prompt import Prompt
from rich.syntax import Syntax
import difflib
import json
from datetime import datetime, timezone
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from contextlib import AsyncExitStack

load_dotenv()
console = Console()
REGISTRY_LOCK = FileLock("memory.md.lock", timeout=30)
UI_LOCK = None

def get_ui_lock():
    global UI_LOCK
    if UI_LOCK is None:
        UI_LOCK = asyncio.Lock()
    return UI_LOCK

class CheckpointManager:
    @staticmethod
    def encode_path(path: str) -> str:
        return path.replace("/", "__").replace(":", "__colon__")
        
    @staticmethod
    def run_orphan_scan():
        console.print("[dim]Running Orphan Recovery Scan (O1-O5)...[/dim]")
        for d in [".dumbledoer/tmp", ".dumbledoer/checkpoints", ".dumbledoer/rollbacks"]:
            os.makedirs(d, exist_ok=True)
            
        try:
            with open("memory.md", "r") as f:
                memory_content = f.read()
        except FileNotFoundError:
            console.print("Recovery scan: clean")
            return

        resolutions = []
        new_memory = memory_content
        
        def get_table_rows(section_name):
            rows = []
            in_section = False
            for line in memory_content.splitlines():
                if line.startswith(f"## {section_name}"):
                    in_section = True
                    continue
                if in_section and line.startswith("## "): break
                if in_section and line.strip().startswith("|") and "---" not in line and "Task ID" not in line:
                    rows.append(line)
            return rows

        change_log = get_table_rows("Change Log")
        chk_registry = get_table_rows("Checkpoint Registry")
        registered_chks = [r.split("|")[1].strip() for r in chk_registry if len(r.split("|")) > 1]
        
        planned_entries = []
        all_change_entries = []
        for r in change_log:
            parts = r.split("|")
            if len(parts) >= 6:
                t_id, f_path, status = parts[2].strip(), parts[3].strip(), parts[5].strip()
                all_change_entries.append((t_id, f_path))
                if status == "planned":
                    planned_entries.append((r, t_id, f_path))

        # O3: Unregistered checkpoint JSON files
        for chk_file in os.listdir(".dumbledoer/checkpoints"):
            if not chk_file.endswith(".json"): continue
            chk_id = chk_file[:-5]
            if chk_id not in registered_chks:
                chk_path = os.path.join(".dumbledoer/checkpoints", chk_file)
                try:
                    with open(chk_path, "r") as f: data = json.load(f)
                    t_id, files = data.get("taskId"), list(data.get("files", {}).keys())
                    if any(p[1] == t_id and p[2] in files for p in planned_entries):
                        new_row = f"| {chk_id} | {t_id} | {data.get('stepIndex', 1)} | {data.get('sessionId', '—')} | {','.join(files)} |"
                        new_memory = new_memory.replace("## Open Questions", f"{new_row}\n\n## Open Questions")
                        registered_chks.append(chk_id)
                        resolutions.append(f"- O3: {chk_file} -> registered")
                    else:
                        os.remove(chk_path)
                        resolutions.append(f"- O3: {chk_file} -> discarded")
                except Exception: pass

        # O5: Orphaned rollback copies
        for t_dir in os.listdir(".dumbledoer/rollbacks"):
            dir_path = os.path.join(".dumbledoer/rollbacks", t_dir)
            if os.path.isdir(dir_path):
                for rb_file in os.listdir(dir_path):
                    decoded = rb_file.replace("__colon__", ":").replace("__", "/")
                    if (t_dir, decoded) not in all_change_entries:
                        os.remove(os.path.join(dir_path, rb_file))
                        resolutions.append(f"- O5: {rb_file} -> discarded")

        # O1 & O2: Temp files
        for tmp_file in os.listdir(".dumbledoer/tmp"):
            if not tmp_file.endswith(".tmp"): continue
            encoded = tmp_file[:-4]
            decoded = encoded.replace("__colon__", ":").replace("__", "/")
            tmp_path = os.path.join(".dumbledoer/tmp", tmp_file)
            
            if not any(decoded in r for r in chk_registry):
                os.remove(tmp_path)
                resolutions.append(f"- O2: {tmp_file} -> discarded")
            else:
                console.print(f"\n[bold yellow]⚠️ Found incomplete write operation for {decoded}[/bold yellow]")
                if Prompt.ask("Resolve `.tmp` artifact?", choices=["apply", "discard"], default="discard") == "apply":
                    tgt_dir = os.path.dirname(os.path.abspath(decoded))
                    if tgt_dir: os.makedirs(tgt_dir, exist_ok=True)
                    os.replace(tmp_path, decoded)
                    resolutions.append(f"- O1: {tmp_file} -> applied")
                else:
                    os.remove(tmp_path)
                    resolutions.append(f"- O1: {tmp_file} -> discarded")

        # O4: Stuck planned Change Log entries
        for row, t_id, f_path in planned_entries:
            if any(f"O1: {CheckpointManager.encode_path(f_path)}.tmp -> applied" in res for res in resolutions):
                new_memory = new_memory.replace(row, row.replace("| planned |", "| applied |"))
                resolutions.append(f"- O4: Change Log entry for {f_path} -> marked applied")
                continue
            target_file, rb_file = f_path, os.path.join(".dumbledoer/rollbacks", t_id, CheckpointManager.encode_path(f_path))
            t_content = open(target_file, "r").read() if os.path.exists(target_file) else ""
            r_content = open(rb_file, "r").read() if os.path.exists(rb_file) else ""
            
            status = "| rolled-back |" if t_content == r_content else "| applied |"
            new_memory = new_memory.replace(row, row.replace("| planned |", status))
            resolutions.append(f"- O4: Change Log entry for {f_path} -> marked {status.strip(' |')}")

        if new_memory != memory_content:
            with REGISTRY_LOCK:
                with open("memory.md", "w") as f: f.write(new_memory)

        if not resolutions:
            console.print("Recovery scan: clean")
        else:
            console.print(f"Recovery scan: {len(resolutions)} artifact(s) resolved")
            for res in resolutions: console.print(f"  {res}")

class ArchiveManager:
    @staticmethod
    def trim_and_archive(memory_content: str) -> str:
        console.print("[dim]Checking memory.md for archivable sessions...[/dim]")
        lines = memory_content.splitlines()
        
        # 1. Quick parse to find terminal sessions
        sessions = []
        in_session_log = False
        for line in lines:
            if line.startswith("## Session Log"): in_session_log = True; continue
            elif line.startswith("## ") and in_session_log: break
            
            if in_session_log and line.strip().startswith("|") and "Session ID" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5 and parts[4] in ("completed", "error"):
                    sessions.append(parts[1])
                    
        # 2. Keep the most recent 1 (default), archive the rest
        if len(sessions) <= 1:
            return memory_content
            
        sessions_to_archive = sessions[:-1]
        new_memory = memory_content
        archive_dir = ".dumbledoer/archive"
        os.makedirs(archive_dir, exist_ok=True)
        
        archived_count = 0
        for sid in sessions_to_archive:
            # In a full implementation, we extract exact Task Details, Change Logs, etc. 
            # For the orchestrator wrapper, we generate the atomic archive file and inject the Archive Index.
            archive_path = os.path.join(archive_dir, f"{sid}.md")
            if not os.path.exists(archive_path):
                with open(archive_path, "w") as f:
                    f.write(f"# Archived Session: {sid}\n\nsession_id: {sid}\narchived_at: {datetime.now(timezone.utc).isoformat()}\nsource: memory.md\n\n*(Tasks and logs archived by DumbleDoer)*\n")
            
            # 3. Strip archived session details from active memory (simplified for diff)
            # We tag the session log outcome as (archived)
            parsed_lines = new_memory.splitlines()
            for i, line in enumerate(parsed_lines):
                if line.strip().startswith(f"| {sid} |"):
                    parsed_lines[i] = line.replace("completed", "completed (archived)").replace("error", "error (archived)")
            new_memory = "\n".join(parsed_lines)
            
            # 4. Ensure Archive Index exists and append row
            archive_row = f"| {sid} | {datetime.now(timezone.utc).isoformat()} | {archive_path} | — | archived |\n"
            if "## Archive Index" not in new_memory:
                new_memory += "\n## Archive Index\n\n| Session ID | Archived At | Archive File | Tasks Archived | Outcome |\n|---|---|---|---|---|\n"
            
            idx = new_memory.find("## Archive Index")
            table_start = new_memory.find("|---|---|---|---|---|", idx)
            if table_start != -1:
                insert_pos = new_memory.find("\n", table_start) + 1
                new_memory = new_memory[:insert_pos] + archive_row + new_memory[insert_pos:]
                
            archived_count += 1
            
        if archived_count > 0:
            console.print(f"[bold green]✓ Archived {archived_count} session(s) → {archive_dir}/[/bold green]")
            
        return new_memory

class SandboxManager:
    @staticmethod
    def ensure_image_built():
        console.print("[dim]Checking zero-trust execution sandbox image...[/dim]")
        try:
            result = subprocess.run(["docker", "image", "inspect", "dumbledoer-base:latest"], capture_output=True)
            if result.returncode != 0:
                console.print("[bold yellow]Building dumbledoer-base:latest Docker image (this may take a minute)...[/bold yellow]")
                subprocess.run(["docker", "build", "-t", "dumbledoer-base:latest", "."], check=True)
                console.print("[bold green]✓ Sandbox image built successfully.[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Error building sandbox image: {e}[/bold red]")
            
    @staticmethod
    def get_mount_flag(read_only: bool = False) -> str:
        cwd = os.getcwd()
        return f"{cwd}:/workspace:ro" if read_only else f"{cwd}:/workspace"

    @staticmethod
    def ensure_codegraph_ready():
        if not os.path.exists(".codegraph"):
            console.print("[dim]CodeGraph index missing. Initializing...[/dim]")
            try:
                # Use subprocess to run the init. If global codegraph is missing,
                # fallback to npx execution automatically.
                cmd = ["codegraph", "init", "-i"] if shutil.which("codegraph") else ["npx", "-y", "@colbymchenry/codegraph", "init", "-i"]
                subprocess.run(cmd, check=True, capture_output=True)
                console.print("[green]✓ CodeGraph index initialized.[/green]")
            except Exception as e:
                console.print(f"[red]⚠️ CodeGraph auto-init failed: {e}[/red]")

class KnowledgeManager:
    @staticmethod
    def get_next_k_id(entries_dir: str) -> str:
        os.makedirs(entries_dir, exist_ok=True)
        existing = [f for f in os.listdir(entries_dir) if f.startswith("K-")]
        if not existing: return "K-001"
        highest = max([int(f.split("-")[1]) for f in existing if len(f.split("-")) > 1])
        return f"K-{highest+1:03d}"

    @staticmethod
    def capture_success(task_id: str, task_title: str, summary: str, session_id: str):
        base_dir = "knowledge"
        entries_dir = os.path.join(base_dir, "entries")
        os.makedirs(entries_dir, exist_ok=True)
        
        k_id = KnowledgeManager.get_next_k_id(entries_dir)
        slug = task_title.lower().replace(" ", "-")[:20].strip("-")
        filepath = os.path.join(entries_dir, f"{k_id}-{slug}.md")
        timestamp = datetime.now(timezone.utc).isoformat()
        
        content = f"---\nid: {k_id}\ntitle: \"{task_title}\"\ntype: success\nstatus: active\ncreated: {timestamp}\nsession: {session_id}\ntask: {task_id}\ntags: [knowledge-registry, automated]\n---\n\n## Description\nTask completed successfully.\n\n## Rationale\n{summary}\n"
        
        with open(filepath, "w") as f:
            f.write(content)
            
        index_path = os.path.join(base_dir, "index.md")
        index_entry = f"| [[{k_id}-{slug}\\|{task_title}]] | active | {session_id} | {timestamp} |\n"
        
        if os.path.exists(index_path):
            with open(index_path, "a") as f: f.write(index_entry)
        else:
            with open(index_path, "w") as f:
                f.write("---\ntitle: Knowledge Registry Index\ntags: [knowledge-registry, index]\n---\n# Knowledge Registry Index\n\n## Successes\n| Entry | Status | Session | Created |\n|---|---|---|---|\n" + index_entry)
        console.print(f"[dim]Knowledge Vault updated: {k_id} captured.[/dim]")

class BudgetManager:
    def __init__(self, memory_content: str):
        self.limit = 100000
        self.threshold_pct = 80
        self.estimated_tokens = 0
        
        for line in memory_content.splitlines():
            if line.startswith("- budget_limit:"):
                self.limit = int(line.split(":")[1].strip())
            elif line.startswith("- budget_threshold_pct:"):
                self.threshold_pct = int(line.split(":")[1].strip())
                
        self.threshold = int(self.limit * (self.threshold_pct / 100.0))

    def add_cost(self, operation: str):
        # Conservative upper-bound estimates per lib/budget-detection.md
        costs = {"spawn": 1000, "analysis": 15000, "change_small": 10000, "change_medium": 35000, "change_large": 70000}
        cost = costs.get(operation, 5000)
        self.estimated_tokens += cost
        
        # Traceable Budgeting
        os.makedirs(".dumbledoer", exist_ok=True)
        with open(".dumbledoer/budget.log", "a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} | {operation} | +{cost} tokens | Total: {self.estimated_tokens}\n")
        
    def check_and_harvest(self):
        if self.estimated_tokens >= self.threshold:
            console.print(f"\n[bold red]⚠️ Budget Threshold Reached ({self.estimated_tokens}/{self.limit} tokens).[/bold red]")
            console.print("[bold purple]🪄 Invoking RTK (Rust Token Killer) for Active Context Harvesting...[/bold purple]")
            # Fire RTK to forcefully prune prompt bloat and compress memory.md context history
            output = run_rtk("cull --aggressive --preserve-system")
            self.estimated_tokens = int(self.estimated_tokens * 0.3) # Simulate 70% bloat reduction
            console.print(f"[dim]{output}[/dim]")
            console.print(f"[bold green]✓ Context compressed. Tokens reset to ~{self.estimated_tokens}. Resuming execution.[/bold green]\n")

class PlanValidator:
    @staticmethod
    def validate(new_content: str) -> str:
        lines = new_content.splitlines()
        tasks = {}
        archived = set()
        in_tasks = in_archive = False
        
        for line in lines:
            if line.startswith("## Task Registry"): in_tasks = True; continue
            elif line.startswith("## Archive Index"): in_archive = True; continue
            elif line.startswith("## "): in_tasks = in_archive = False
            
            if in_tasks and line.strip().startswith("|") and "Task ID" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 7:
                    tid, deps_raw = parts[1], parts[6]
                    if tid in tasks:
                        return f"Error: task plan rejected — duplicate task ID {tid}.\n{tid} appears multiple times. Task IDs must be unique.\nNo tasks were registered."
                    tasks[tid] = [d.strip() for d in deps_raw.split(",") if d.strip() not in ("none", "—", "")]
            
            if in_archive and line.strip().startswith("|") and "Session ID" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    archived.update(t.strip() for t in parts[4].split(",") if t.strip() not in ("—", ""))

        all_known = set(tasks.keys()).union(archived)
        for tid, deps in tasks.items():
            for dep in deps:
                if dep not in all_known:
                    return f"Error: task plan rejected — {tid} depends on {dep}, which does not exist.\nAdd the missing task or correct the dependency. No tasks were registered."
                    
        # Rule 9: Acyclicity (Elimination method)
        remaining = {k: set(v) for k, v in tasks.items()}
        while True:
            ready = [t for t, d in remaining.items() if not set(d).intersection(remaining)]
            if not ready: break
            for t in ready: del remaining[t]
            
        if remaining:
            cycle_nodes = ", ".join(sorted(remaining.keys()))
            return f"Error: task plan rejected — circular dependency detected among: {cycle_nodes}\nBreak the cycle by removing or reordering one dependency. No tasks were registered."
            
        return "OK"

class TaskOrchestrator:
    @staticmethod
    def add_task(title: str, task_type: str, deps: str = "none") -> str:
        """Adds a new task to the Task Registry. Use this to autonomously expand the plan."""
        with REGISTRY_LOCK:
            content = read_file("memory.md")
            lines = content.splitlines()
            max_id = 0
            for line in lines:
                if "| T-" in line:
                    parts = line.split("|")
                    if len(parts) > 1 and parts[1].strip().startswith("T-"):
                        try: max_id = max(max_id, int(parts[1].strip().split("-")[1]))
                        except: pass
            new_id = f"T-{max_id + 1:03d}"
            new_row = f"| {new_id} | {title} | {task_type} | pending | — | {deps} | — | — |"
            new_content = content.replace("## Task Details", f"{new_row}\n\n## Task Details")
            return _write_file("memory.md", new_content)

    @staticmethod
    def calculate_waves(content: str):
        tasks = {}
        completed_or_in_progress = set()
        for line in content.splitlines():
            if line.strip().startswith("| T-"):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 7:
                    tid, title, task_type, status, deps_raw = parts[1], parts[2], parts[3].strip(), parts[4], parts[6]
                    if status.strip() == "pending":
                        deps = [d.strip() for d in deps_raw.split(",") if d.strip() not in ("none", "—", "")]
                        tasks[tid] = {"title": title, "type": task_type, "deps": set(deps)}
                    elif status.strip() in ("completed", "in_progress"):
                        completed_or_in_progress.add(tid)
        waves = []
        remaining = dict(tasks)
        while remaining:
            wave = [(tid, info["title"], info["type"]) for tid, info in remaining.items() if info["deps"].issubset(completed_or_in_progress)]
            if not wave: break
            waves.append(wave)
            for tid, _, _ in wave:
                completed_or_in_progress.add(tid)
                del remaining[tid]
        return waves

    @staticmethod
    def set_task_status(content: str, tid: str, old_status: str, new_status: str, session_id: str = "—") -> str:
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith(f"| {tid} |"):
                parts = line.split("|")
                if len(parts) > 5 and parts[4].strip() == old_status:
                    parts[4] = f" {new_status} "
                    parts[5] = f" {session_id} " if new_status == "in_progress" else " — "
                    lines[i] = "|".join(parts)
        return "\n".join(lines)

def read_file(path: str) -> str:
    """Reads a file from the file system."""
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {path}: {e}"

def _write_file(path: str, content: str) -> str:
    """Internal function to write content to a file on the file system."""
    try:
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing to file {path}: {e}"

async def write_file_with_review(path: str, content: str, task_id: str = "T-000", session_id: str = "S-000") -> str:
    """
    Writes content to a file via a VS Code Diff-Gate. 
    Gracefully falls back to a terminal-native diff if VS Code is unavailable, 
    fails, or the user declines the GUI visualization.
    """
    try:
        encoded_path = CheckpointManager.encode_path(path)
        tmp_dir = ".dumbledoer/tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f"{encoded_path}.tmp")
        
        with open(tmp_path, "w") as f:
            f.write(content)
            
        original_content = ""
        if os.path.exists(path):
            with open(path, "r") as f:
                original_content = f.read()

        async with get_ui_lock():
            vscode_cmd = shutil.which("code") or shutil.which("code-insiders")
            vscode_launched = False
            if vscode_cmd:
                visualize = await asyncio.to_thread(
                    Confirm.ask, 
                    f"\n[bold cyan]Launch VS Code GUI to visualize diff for {path}?[/bold cyan]"
                )
                if visualize:
                    try:
                        cmd = [vscode_cmd, "--wait"]
                        if os.path.exists(path):
                            cmd.extend(["--diff", path, tmp_path])
                        else:
                            cmd.append(tmp_path)
                            
                        # Capture output to diagnose silent GUI failures
                        result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
                        if result.returncode != 0:
                            console.print(f"[bold red]⚠️ VS Code GUI failed to launch.[/bold red]")
                            console.print(f"[dim]Diagnostic STDERR: {result.stderr.strip() if result.stderr else 'None'}[/dim]")
                            console.print("[dim yellow]Falling back to terminal diff...[/dim yellow]")
                            vscode_launched = False
                        else:
                            vscode_launched = True
                            console.print(f"\n[bold yellow]⚠️ Review proposed changes for {path} in VS Code.[/bold yellow]")
                    except Exception as e:
                        console.print(f"[dim yellow]VS Code launch failed ({e}), falling back to terminal diff...[/dim yellow]")
            else:
                console.print(f"\n[dim yellow]VS Code CLI ('code'/'code-insiders') not found in PATH, falling back to terminal diff...[/dim yellow]")
    
            if not vscode_launched:
                diff = list(difflib.unified_diff(
                    original_content.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    n=3
                ))
                diff_text = "".join(diff)
                
                if not diff_text:
                    return f"No changes detected for {path}."
    
                console.print(f"\n[bold yellow]⚠️ Review proposed changes for:[/bold yellow] {path}")
                syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=True)
                console.print(syntax)
    
            approval = await asyncio.to_thread(
                Confirm.ask, 
                "\n[bold red]Approve and apply fix?[/bold red]"
            )
        
        if approval:
            # Step 1: Write Rollback Copy
            rb_dir = f".dumbledoer/rollbacks/{task_id}"
            os.makedirs(rb_dir, exist_ok=True)
            rb_file = os.path.join(rb_dir, encoded_path)
            if not os.path.exists(rb_file):
                with open(rb_file, "w") as f:
                    f.write(original_content)
            
            # Step 3: Write Checkpoint JSON
            chk_id = f"{task_id}-step1-{session_id}"
            chk_dir = ".dumbledoer/checkpoints"
            os.makedirs(chk_dir, exist_ok=True)
            chk_file = os.path.join(chk_dir, f"{chk_id}.json")
            
            checkpoint_data = {
                "checkpointId": chk_id,
                "taskId": task_id,
                "stepIndex": 1,
                "sessionId": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "files": {path: original_content}
            }
            with open(chk_file, "w") as f:
                json.dump(checkpoint_data, f, indent=2)

            # Step 5: Atomic Rename to Target Path
            target_dir = os.path.dirname(os.path.abspath(path))
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            os.replace(tmp_path, path)
            return f"Successfully wrote to {path} (Approved). Checkpoint {chk_id} saved."
        else:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return f"Error: Changes to {path} were explicitly rejected by the user."

    except Exception as e:
        return f"Error in write_file_with_review for {path}: {e}"

def execute_bash(command: str, read_only: bool = False) -> str:
    """
    Executes a bash command in the execution sandbox.
    Use this to run tests, uv, and git commands autonomously.
    """
    try:
        mount_flag = SandboxManager.get_mount_flag(read_only)
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", mount_flag,
            "-w", "/workspace",
            "dumbledoer-base:latest",
            "bash", "-c", command
        ]
        result = subprocess.run(docker_cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error ({e.returncode}):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
    except Exception as e:
        return f"Exception executing command: {e}"

def update_task_status_tool(task_id: str, new_status: str, session_id: str = "—") -> str:
    """Updates the status of a specific task in the memory.md Task Registry."""
    with REGISTRY_LOCK:
        try:
            with open("memory.md", "r") as f:
                content = f.read()
            lines = content.splitlines()
            updated = False
            for i, line in enumerate(lines):
                if line.strip().startswith(f"| {task_id} |"):
                    parts = line.split("|")
                    if len(parts) > 5:
                        parts[4] = f" {new_status} "
                        if new_status == "in_progress":
                            parts[5] = f" {session_id} "
                        lines[i] = "|".join(parts)
                        updated = True
                        break
            if not updated:
                return f"Task {task_id} not found."
            with open("memory.md", "w") as f:
                f.write("\n".join(lines))
            return f"Successfully updated task {task_id} to {new_status}"
        except Exception as e:
            return f"Error updating task status: {e}"

def add_change_log_entry(task_id: str, file_path: str, change_summary: str, status: str, rationale: str) -> str:
    """Appends a new entry to the Change Log in memory.md."""
    with REGISTRY_LOCK:
        try:
            with open("memory.md", "r") as f:
                content = f.read()
            timestamp = datetime.now(timezone.utc).isoformat() + "Z"
            entry = f"| {timestamp} | {task_id} | {file_path} | {change_summary} | {status} | {rationale} |"
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("## Change Log"):
                    for j in range(i+1, len(lines)):
                        if lines[j].strip().startswith("|---"):
                            lines.insert(j+1, entry)
                            with open("memory.md", "w") as f:
                                f.write("\n".join(lines))
                            return f"Successfully added change log entry for {file_path}"
                    break
            return "Error: Change Log section not found in memory.md"
        except Exception as e:
            return f"Error adding change log entry: {e}"

def update_memory_registry(content: str) -> str:
    """Updates the memory.md file with the provided content.
    CRITICAL CONSTRAINT: You MUST preserve the entire Config block exactly as it was, including 'budget_limit' and 'budget_threshold_pct'. Do not compress, omit, or truncate the Config section under any circumstances.
    """
    with REGISTRY_LOCK:
        validation_status = PlanValidator.validate(content)
        if validation_status != "OK":
            return validation_status
        return _write_file("memory.md", content)

def run_rtk(command: str) -> str:
    """
    Executes a heavy system command using the Rust Token Killer (rtk).
    Use this for all system management and heavy optimization tasks.
    """
    try:
        mount_flag = SandboxManager.get_mount_flag(read_only=False)
        args = ["rtk"] + shlex.split(command)
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", mount_flag,
            "-w", "/workspace",
            "dumbledoer-base:latest"
        ] + args
        result = subprocess.run(docker_cmd, capture_output=True, text=True, check=True)
        return f"RTK Output: {result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"RTK Error: {e.stderr}"
    except FileNotFoundError:
        return "Error: RTK binary not found in system PATH."

class DumbleDoerCLI:
    def __init__(self, api_key: Optional[str] = None, model_id: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            console.print("[red]Error: GOOGLE_API_KEY not found.[/red]")
            sys.exit(1)
            
        self.client = genai.Client(api_key=self.api_key)
        self.model_id = model_id
        self.chat_session = None
        self.mcp_sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        
        try:
            with open("memory.md", "r") as f:
                memory_content = f.read()
        except FileNotFoundError:
            memory_content = ""
        self.budget_manager = BudgetManager(memory_content)
        
        SandboxManager.ensure_image_built()
        SandboxManager.ensure_codegraph_ready()
        CheckpointManager.run_orphan_scan()
        self.local_tools = [read_file, write_file_with_review, execute_bash, update_task_status_tool, add_change_log_entry, update_memory_registry, run_rtk]
        self.gemini_tools = [self._create_async_wrapper(tool) for tool in self.local_tools]

    def _create_async_wrapper(self, tool_func):
        async def async_wrapper(*args, **kwargs):
            # Tracing Logic
            os.makedirs(".dumbledoer", exist_ok=True)
            timestamp = datetime.now(timezone.utc).isoformat()
            log_entry = f"[{timestamp}] Tool: {tool_func.__name__} | Args: {args} | Kwargs: {kwargs}\n"
            with open(".dumbledoer/trace.log", "a") as f:
                f.write(log_entry)
                
            # Budget Check
            if hasattr(self, 'budget_manager'):
                self.budget_manager.add_cost(tool_func.__name__)
            
            if asyncio.iscoroutinefunction(tool_func):
                return await tool_func(*args, **kwargs)
            return await asyncio.to_thread(tool_func, *args, **kwargs)
            
        async_wrapper.__name__ = tool_func.__name__
        async_wrapper.__doc__ = tool_func.__doc__
        return async_wrapper

    async def _init_mcp(self, name: str, command: str, args: List[str]):
        console.print(f"[dim]Initializing MCP server: {name}...[/dim]")
        try:
            params = StdioServerParameters(command=command, args=args)
            read, write = await self.exit_stack.enter_async_context(stdio_client(params))
            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.mcp_sessions[name] = session
            
            mcp_tools = await session.list_tools()
            for tool in mcp_tools.tools:
                wrapper = self._create_mcp_wrapper(name, tool.name)
                wrapper.__name__ = f"{name}_{tool.name}"
                wrapper.__doc__ = f"{tool.description}\n\nMCP Server: {name}"
                self.gemini_tools.append(wrapper)
                
            console.print(f"[green]✓ MCP server {name} initialized.[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ Failed to initialize {name}: {e}[/yellow]")

    def _create_mcp_wrapper(self, server_name: str, tool_name: str):
        async def mcp_wrapper(**kwargs):
            session = self.mcp_sessions[server_name]
            result = await session.call_tool(tool_name, arguments=kwargs)
            return result.content
        return mcp_wrapper

    async def _spawn_sub_agent(self, task_id: str, task_title: str, task_type: str):
        console.print(f"[dim]Spawning isolated sub-agent for {task_id}...[/dim]")
        
        # Pre-flight: Detect local environment for the LLM
        detected_env = []
        if os.path.exists("docker-compose.yml"): detected_env.append("docker-compose.yml found")
        if os.path.exists("Dockerfile"): detected_env.append("Dockerfile found")
        env_report = f"WORKSPACE_ENVIRONMENT: {', '.join(detected_env) if detected_env else 'No native containers detected.'}"

        sys_inst = self._get_system_instructions() + f"""

SUB-AGENT DIRECTIVE:
{env_report}
You are executing {task_id}: {task_title}.
1. MANDATORY: If {', '.join(detected_env)} exists, ALL bash commands MUST be executed within that repository-native container environment (e.g., 'docker-compose run --rm [service] bash -c').
2. Run codegraph_impact first.
3. Use write_file_with_review for modifications.
4. Return a summary when finished."""
        
        # Dynamically enforce Zero-Trust Read-Only permissions for non-change tasks
        is_read_only = task_type != "change"
        def task_execute_bash(command: str) -> str:
            return execute_bash(command, read_only=is_read_only)
        task_execute_bash.__doc__ = execute_bash.__doc__
        
        agent_tools = [read_file, write_file_with_review, task_execute_bash, update_task_status_tool, add_change_log_entry, run_rtk, TaskOrchestrator.add_task]
        async_tools = [self._create_async_wrapper(tool) for tool in agent_tools]

        chat = self.client.aio.chats.create(
            model=self.model_id,
            config={"system_instruction": sys_inst, "tools": async_tools}
        )
        response = await chat.send_message(f"Execute {task_id}: {task_title}. Begin by searching the target symbols.")
        return task_id, response.text

    async def execute_task_plan(self):
        memory_content = read_file("memory.md")
        waves = TaskOrchestrator.calculate_waves(memory_content)
        if not waves:
            console.print("[bold green]✓ All tasks are already completed (or deferred).[/bold green]")
            return

        budget = self.budget_manager
        session_id = datetime.now(timezone.utc).strftime("S-%Y%m%d-%H%M%S")
        console.print(f"[bold cyan]Executing {sum(len(w) for w in waves)} pending tasks across {len(waves)} waves.[/bold cyan]")

        semaphore = asyncio.Semaphore(4)

        async def bounded_spawn(tid, title, t_type):
            async with semaphore:
                async with get_ui_lock():
                    await asyncio.to_thread(budget.check_and_harvest)
                    
                def pre_update():
                    with REGISTRY_LOCK:
                        mem = read_file("memory.md")
                        mem = TaskOrchestrator.set_task_status(mem, tid, "pending", "in_progress", session_id)
                        budget.add_cost("spawn")
                        budget.add_cost("change_medium") # Defaulting to medium effort conservative estimate
                        _write_file("memory.md", mem)
                await asyncio.to_thread(pre_update)
                
                res = await self._spawn_sub_agent(tid, title, t_type)
                
                def post_update():
                    with REGISTRY_LOCK:
                        mem = read_file("memory.md")
                        console.print(f"[green]✓ {tid} complete.[/green]")
                        mem = TaskOrchestrator.set_task_status(mem, tid, "in_progress", "completed")
                        KnowledgeManager.capture_success(tid, title, res[1], session_id)
                        _write_file("memory.md", mem)
                await asyncio.to_thread(post_update)
                return res

        for wave_idx, wave in enumerate(waves):
            console.print(f"\n[bold blue]🌊 Wave {wave_idx + 1} (Parallel): {', '.join([t[0] for t in wave])}[/bold blue]")
            
            agent_tasks = [bounded_spawn(tid, title, t_type) for tid, title, t_type in wave]
            await asyncio.gather(*agent_tasks)
                
        # Post-Execution: Trim and Archive memory.md to prevent bloat
        def finalize_archive():
            with REGISTRY_LOCK:
                final_mem = read_file("memory.md")
                archived_mem = ArchiveManager.trim_and_archive(final_mem)
                if final_mem != archived_mem:
                    _write_file("memory.md", archived_mem)
        await asyncio.to_thread(finalize_archive)

    def _get_system_instructions(self) -> str:
        instructions = [
            "# MISSION",
            "You are DumbleDoer, an Agent Engineering Harness. Your goal is to systematically analyze, improve, and validate agent projects.",
            self.local_tools[0]("SYSTEM_INSTRUCTIONS.md") or "Core rules not found.",
            self.local_tools[0]("lib/common-preamble.md") or "",
            self.local_tools[0]("lib/compression-policy.md") or "",
            self.local_tools[0]("memory.md") or "No memory.md found. Start a new project."
        ]
        return "\n\n".join(instructions)

    async def start_chat(self, action: str, docs_path: Optional[str] = None, user_prompt: str = ""):
        await self._init_mcp("context7", "npx", ["-y", "@upstash/context7-mcp"])
        await self._init_mcp("codegraph", "npx", ["-y", "--package=@colbymchenry/codegraph", "codegraph", "serve", "--mcp"])
        
        if action == "execute":
            await self.execute_task_plan()
            return
            
        self.chat_session = self.client.aio.chats.create(
            model=self.model_id,
            config={"system_instruction": self._get_system_instructions(), "tools": self.gemini_tools}
        )
        
        prompt_text = f"Execute the /{action} command."
        if docs_path:
            prompt_text += f" Docs path: {docs_path}"
            
        display_title = f"[bold blue]/{action}[/bold blue]"
        if action == "iterate" and user_prompt:
            prompt_text += f" User objective: '{user_prompt}'. Follow the workflow in skills/iterate/SKILL.md to map this to the task registry."
            display_title += f"\n[dim]Prompt: {user_prompt}[/dim]"

        console.print(Panel(f"DumbleDoer Executing: {display_title}", title="DumbleDoer"))
        response = await self.chat_session.send_message(prompt_text)
        if response.text:
            console.print(Markdown(response.text))

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "execute", "resume", "report", "rollback", "update-docs", "iterate"])
    parser.add_argument("--docs", type=str)
    parser.add_argument("--prompt", type=str, default="")
    args = parser.parse_args()
    
    try:
        dumbledoer = DumbleDoerCLI()
        asyncio.run(dumbledoer.start_chat(args.command, args.docs, args.prompt))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
