from dumbledoer.core.locks import _MEMORY_MUTEX, _KNOWLEDGE_MUTEX, _REGISTRY_LOCK, get_registry_lock
import sys
import os
import subprocess
import asyncio



import re
import glob
import shutil
import filecmp
from filelock import FileLock
import filelock


class ASTMemoryMapper:
    @staticmethod
    def locate_heading_block(content: str, header_level: str, header_title: str) -> tuple[int, int]:
        lines = content.splitlines()
        start_idx = -1
        end_idx = -1
        
        target_title = header_title.lower().strip()
        in_code = False
        
        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                in_code = not in_code
            if not in_code and line.startswith(f"{header_level} "):
                clean_line = line[len(header_level)+1:].lower().strip().rstrip('#').strip()
                clean_line = re.sub(r'[*_]{1,2}', '', clean_line).strip()
                if clean_line == target_title:
                    start_idx = i
                    break
                    
        if start_idx != -1:
            levels = [header_level[:j] + " " for j in range(1, len(header_level)+1)]
            in_code = False
            for i in range(start_idx + 1, len(lines)):
                if lines[i].strip().startswith("```"):
                    in_code = not in_code
                if not in_code and any(lines[i].startswith(lvl) for lvl in levels):
                    end_idx = i
                    break
            if end_idx == -1:
                end_idx = len(lines)
                
        return start_idx, end_idx

    @staticmethod
    def append_to_markdown_table(file_path: str, header_title: str, new_row: str):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", header_title)
            if start_idx == -1: return False
            lines = content.splitlines()
            block = lines[start_idx:end_idx]
            insert_idx = end_idx
            for i in range(len(block)-1, -1, -1):
                if block[i].strip():
                    insert_idx = start_idx + i + 1
                    break
            lines.insert(insert_idx, new_row)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            return True
        except Exception:
            return False

# Deprecate the old block-replace tool
# async def update_memory_registry(section_header: str, new_content: str) -> str: ...

# Create a surgical row-update tool exposed to the LLM
async def update_task_registry_row(task_id: str, new_status: str, new_owner: str = "—") -> str:
    """Surgically updates a task's status in the registry without overwriting sibling tasks."""
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            try:
                # 1. We read the fresh state inside the lock, immune to stale LLM context
                state = TaskRegistryState()
                tasks = state._load_tasks_unlocked()
                
                if task_id not in tasks:
                    return f"Error: Task {task_id} not found."
                
                tasks[task_id]["status"] = new_status
                tasks[task_id]["owner"] = new_owner
                
                # 2. Write exactly the parsed row back out
                state._sync_to_markdown_unlocked(tasks)
                return f"Successfully updated {task_id} to {new_status}."
            except Exception as e:
                return f"Error updating registry: {e}"
        

class CheckpointManager:
    async def write_rollback_copy(self, target_path: str, rollback_path: str):
        if os.path.exists(rollback_path):
            return
        if os.path.exists(target_path):
            os.makedirs(os.path.dirname(rollback_path), exist_ok=True)
            shutil.copy2(target_path, rollback_path)
            
    async def log_planned_change(self, target_path: str, metadata: dict):
        timestamp = metadata.get("Timestamp", "")
        task_id = metadata.get("Task ID", "")
        summary = metadata.get("Change Summary", "")
        rationale = metadata.get("Rationale", "")
        row = f"| {timestamp} | {task_id} | {target_path} | {summary} | planned | {rationale} |"
        async with _MEMORY_MUTEX:
            async with get_registry_lock():
                ASTMemoryMapper.append_to_markdown_table("memory.md", "Change Log", row)
        
    async def write_checkpoint_json(self, checkpoint_path: str, metadata: dict):
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
        async with _MEMORY_MUTEX:
            async with get_registry_lock():
                ASTMemoryMapper.append_to_markdown_table("memory.md", "Checkpoint Registry", row)
            
    async def stage_tmp_write(self, tmp_path: str, content: str):
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        with open(tmp_path, "w") as f:
            f.write(content)
            
    async def atomic_rename_to_target(self, tmp_path: str, target_path: str):
        os.replace(tmp_path, target_path)
        
    async def log_applied_change(self, target_path: str, metadata: dict):
        timestamp = metadata.get("Timestamp", "")
        task_id = metadata.get("Task ID", "")
        summary = metadata.get("Change Summary", "")
        rationale = metadata.get("Rationale", "")
        row = f"| {timestamp} | {task_id} | {target_path} | {summary} | applied | {rationale} |"
        async with _MEMORY_MUTEX:
            async with get_registry_lock():
                ASTMemoryMapper.append_to_markdown_table("memory.md", "Change Log", row)

class OrphanRecoveryScanner:
    async def run(self, unattended=False):
        async with _MEMORY_MUTEX:
          async with get_registry_lock():
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
                            if len(parts) >= 6:
                                change_log.append({
                                    "chk_id": parts[2],
                                    "target": parts[3],
                                    "status": parts[5],
                                    "line_text": line,
                                })
            except FileNotFoundError:
                pass
    
            from rich.prompt import Confirm
            from rich.console import Console
            console = Console()
            
            planned_chks = [c for c in change_log if c["status"].strip() == "planned"]
            if not planned_chks:
                return
                
            console.print("[yellow]Found unresolved planned changes in ledger. Attempting recovery...[/yellow]")
            new_content = content
            for entry in planned_chks:
                task_id = entry["chk_id"]
                target = entry["target"]
                
                encoded_path = target.replace("/", "__").replace(":", "__colon__")
                possible_rollback = os.path.join(bak_dir, task_id, encoded_path)
                
                bak_file = None
                if os.path.exists(possible_rollback):
                    bak_file = possible_rollback
                else:
                    bak_files = glob.glob(os.path.join(bak_dir, f"*_{encoded_path}.bak"))
                    if bak_files:
                        bak_file = bak_files[0]
                        
                if bak_file:
                    if os.path.exists(target) and filecmp.cmp(target, bak_file, shallow=False):
                        new_status = "rolled-back"
                    else:
                        new_status = "applied"
                else:
                    new_status = "unknown"
                    
                console.print(f"O4: Resolved planned change {task_id} as {new_status}")
                new_line = entry["line_text"].replace("| planned |", f"| {new_status} |")
                new_content = new_content.replace(entry["line_text"], new_line)
                
                # Cleanup shadow tmp
                tmp_files = glob.glob(os.path.join(tmp_dir, f"*_{encoded_path}.tmp"))
                for t in tmp_files:
                    if os.path.exists(t):
                        os.remove(t)
                        
            if new_content != content:
                with open("memory.md", "w", encoding="utf-8") as f:
                    f.write(new_content)

class TaskRegistryState:
    def __init__(self, md_path: str = "memory.md"):
        self.md_path = md_path
        self.lock_path = md_path + ".lock"

    async def load_tasks(self):
        async with get_registry_lock():
            return self._load_tasks_unlocked()

    def _load_tasks_unlocked(self):
        try:
            with open(self.md_path, "r", encoding="utf-8") as f:
                content = f.read()
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Task Registry")
            if start_idx == -1: return {}
            lines = content.splitlines()[start_idx+1:end_idx]
            tasks = {}
            for line in lines:
                if line.strip().startswith("|") and "Task ID" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 9:
                        tasks[parts[1]] = {
                            "id": parts[1],
                            "title": parts[2],
                            "type": parts[3],
                            "status": parts[4],
                            "owner": parts[5],
                            "deps": [d.strip() for d in parts[6].split(',')] if parts[6] not in ('none', '—') else [],
                            "session": parts[7],
                            "checkpoint": parts[8]
                        }
                    elif len(parts) >= 5:
                        tasks[parts[1]] = {
                            "id": parts[1],
                            "title": parts[2],
                            "type": parts[3] if len(parts) > 3 else "unknown",
                            "status": parts[4] if len(parts) > 4 else "unknown",
                            "deps": []
                        }
            return tasks
        except FileNotFoundError:
            return {}

    async def get_tasks(self):
        async with get_registry_lock():
            return self._load_tasks_unlocked()

    async def _sync_to_markdown(self, tasks: dict):
        async with get_registry_lock():
            self._sync_to_markdown_unlocked(tasks)

    def _sync_to_markdown_unlocked(self, tasks: dict):
        try:
            with open(self.md_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Task Registry")
            if start_idx == -1: return
            lines = content.splitlines()

            header_line = next((l for l in lines[start_idx+1:end_idx] if "|" in l and "Task ID" in l), None)
            if header_line:
                headers = [h.strip() for h in header_line.split("|") if h.strip()]
                stat_idx = headers.index("Status") + 1 if "Status" in headers else 4
            else:
                stat_idx = 4

            new_block = []
            for line in lines[start_idx+1:end_idx]:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5 and "Task ID" not in parts[1] and not parts[1].strip().startswith("---"):
                    tid = parts[1].strip()
                    if tid in tasks:
                        if len(parts) > stat_idx:
                            parts[stat_idx] = f" {tasks[tid]['status']} "
                        else:
                            parts[4] = f" {tasks[tid]['status']} "
                        if len(parts) >= 6 and 'owner' in tasks[tid]:
                            parts[5] = f" {tasks[tid]['owner']} "
                        new_block.append("|".join(parts))
                    else:
                        new_block.append(line)
                else:
                    new_block.append(line)
                        
            new_content = "\n".join(lines[:start_idx+1] + new_block + lines[end_idx:])
            with open(self.md_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            raise IOError(f"Critical State Error: Failed to sync task registry to memory.md: {e}")

    async def update_task_status(self, task_id: str, new_status: str):
        # FIX: Add _MEMORY_MUTEX to perfectly align with update_task_registry_row
        async with _MEMORY_MUTEX:
            async with get_registry_lock():
                tasks = self._load_tasks_unlocked()
                if task_id in tasks:
                    tasks[task_id]["status"] = new_status
                    self._sync_to_markdown_unlocked(tasks)

async def read_file(path: str) -> str:
    def _read():
        expanded_path = os.path.expanduser(path)
        with open(expanded_path, "r", encoding="utf-8") as f:
            return f.read()
    try:
        return await asyncio.to_thread(_read)
    except Exception as e:
        return f"Error reading file {path}: {e}"

async def write_file_with_review(path: str, content: str, task_id: str) -> str:
    try:
        try:
            impact_proc = await asyncio.to_thread(
                subprocess.run, 
                ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "impact", path], 
                capture_output=True, text=True
            )
            match = re.search(r"—\s*(\d+)\s+affected symbol", impact_proc.stdout if hasattr(impact_proc, 'stdout') else str(impact_proc))
            if match and int(match.group(1)) > 20:
                return f"Error: CodeGraph impact threshold exceeded ({match.group(1)} symbols > 20). Write blocked to prevent system instability."
        except Exception as e:
            pass

        tmp_dir = ".dumbledoer/tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        import uuid
        encoded_path = path.replace("/", "__").replace(":", "__colon__")
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}_{encoded_path}.tmp")
        
        import time
        from datetime import datetime
        manager = CheckpointManager()
        chk_id = f"chk_{int(time.time())}"
        
        metadata = {
            "Timestamp": datetime.now().isoformat(),
            "Task ID": task_id,
            "Change Summary": f"Update {os.path.basename(path)} via Diff-Gate",
            "Rationale": "User-approved manual write_file_with_review",
            "Checkpoint ID": chk_id,
            "Session ID": "manual",
            "Step": "diff-gate",
            "Files Snapshotted": path
        }
        rollback_path = os.path.join(".dumbledoer", "rollbacks", task_id, encoded_path)
        checkpoint_path = os.path.join(".dumbledoer", "checkpoints", f"{chk_id}.json")
        
        await manager.write_rollback_copy(path, rollback_path)
        await manager.log_planned_change(path, metadata)
        await manager.write_checkpoint_json(checkpoint_path, metadata)
        
        with open(tmp_path, "w") as f:
            f.write(content)
            
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
            
        return f"Successfully applied changes to {path} (Rollback: {rollback_path}, Review: {tmp_path})"
    except Exception as e:
        return f"Error in write_file_with_review for {path}: {e}"

async def add_task(title: str, task_type: str = "change", deps: str = "none", description: str = "", outputs: str = "none", success_criteria: str = "TBD") -> str:
    """Registers a new atomic task to the memory.md Task Registry. Auto-generates the Task ID."""
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            try:
                with open("memory.md", "r", encoding="utf-8") as f:
                    content = f.read()
                
                import re
                existing_ids = re.findall(r'T-(\d{3,4})', content)
                next_num = max([int(x) for x in existing_ids]) + 1 if existing_ids else 1
                task_id = f"T-{next_num:03d}"

                if deps.lower() not in ["none", "—", "-", ""]:
                    for d in [d.strip() for d in deps.split(",")]:
                        if f"| {d} |" not in content and f"### {d}" not in content:
                            return f"Error: Dependency {d} does not exist in memory.md. Task creation rejected."

                reg_start, reg_end = ASTMemoryMapper.locate_heading_block(content, "##", "Task Registry")
                det_start, det_end = ASTMemoryMapper.locate_heading_block(content, "##", "Task Details")
                
                if det_start == -1 or reg_start == -1:
                    return "Error: Header '## Task Registry' or '## Task Details' not found in memory.md"

                lines = content.splitlines()
                
                row = f"| {task_id} | {title} | {task_type} | pending | — | {deps} | — | none |"
                details = f"\n### {task_id}: {title}\n- **Type**: {task_type}\n- **Status**: pending\n- **Owner**: —\n- **Depends On**: {deps}\n- **Assigned Session**: —\n- **Description**: {description}\n- **Inputs**: none\n- **Outputs**: {outputs}\n- **Success Criteria**: {success_criteria}\n- **Estimated Effort**: small\n- **Parallelizable**: yes\n- **CodeGraph Impact**: —\n- **Checkpoint**: none\n- **Resume Instructions**: none\n- **Notes**: —\n"

                # Calculate precise insertion to avoid index drift
                lines.insert(det_end, details)
                
                # Insert registry row at the end of the markdown table
                reg_insert = reg_end
                for i in range(reg_end - 1, reg_start, -1):
                    if lines[i].strip():
                        reg_insert = i + 1
                        break
                lines.insert(reg_insert, row)

                with open("memory.md", "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                    
                return f"Successfully registered task {task_id}."
            except Exception as e:
                return f"Error adding task: {e}"
    

async def record_knowledge(title: str, entry_type: str, description: str, rationale: str, supersedes: str = "none") -> str:
    """Saves a durable learning securely to the Vault using an Async Mutex."""
    async with _KNOWLEDGE_MUTEX:
        async with get_registry_lock():
                try:
                    os.makedirs("knowledge/entries", exist_ok=True)
                    
                    # 1. Native Sequential ID Generation
                    import glob, re
                    existing_entries = glob.glob("knowledge/entries/*.md")
                    highest_num = 0
                    for entry in existing_entries:
                        match = re.search(r'K-(\d+)', os.path.basename(entry))
                        if match:
                            num = int(match.group(1))
                            if num > highest_num:
                                highest_num = num
                                
                    k_id = f"K-{(highest_num + 1):03d}"
                    slug = title.lower().replace(" ", "-")
                    slug = "".join(c for c in slug if c.isalnum() or c == "-")[:25]
                    filename = f"knowledge/entries/{k_id}-{slug}.md"

                    # 2. Handle Supersession (OP-7)
                    if supersedes and supersedes.lower() not in ["none", "—", "-", ""]:
                        sup_list = [s.strip() for s in supersedes.split(",")]
                        for sup_id in sup_list:
                            # Find the file that matches this ID
                            target_files = glob.glob(f"knowledge/entries/{sup_id}-*.md")
                            for tf in target_files:
                                with open(tf, "r", encoding="utf-8") as f_sup:
                                    sup_content = f_sup.read()
                                # Demote status to superseded
                                sup_content = re.sub(r'status:\s*active', 'status: superseded', sup_content, count=1)
                                with open(tf, "w", encoding="utf-8") as f_sup:
                                    f_sup.write(sup_content)

                    # 3. Write New Entry
                    from datetime import datetime
                    content = f"""---
id: {k_id}
title: "{title}"
type: {entry_type}
status: active
created: {datetime.utcnow().isoformat()}Z
session: manual
tags: [knowledge-registry]
---

## Description
{description}

## Rationale
{rationale}
"""
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(content)

                    # 4. Synchronous Index Update
                    if os.path.exists("sync_knowledge.py"):
                        import subprocess
                        subprocess.run([sys.executable, "sync_knowledge.py"], capture_output=True)

                    msg = f"Successfully recorded learning to {filename}"
                    if supersedes and supersedes.lower() not in ["none", "—", "-", ""]:
                        msg += f" (Superseded: {supersedes})"
                    return msg
                except Exception as e:
                    return f"Error recording knowledge: {e}"
                    


async def append_handoff_summary(summary: str):
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
                with open("memory.md", "r", encoding="utf-8") as f:
                    content = f.read()
                start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Session Handoff Summary")
                if start_idx != -1:
                    lines = content.splitlines()
                    content = "\n".join(lines[:start_idx] + [summary.strip()] + lines[end_idx:])
                else:
                    content += f"\n\n{summary}"
                with open("memory.md", "w", encoding="utf-8") as f:
                    f.write(content)


async def read_code_block(file_path: str, symbol_name: str) -> str:
    """Reads a specific function, class, or method from a file using AST parsing. Returns only the relevant code block instead of the entire file."""
    def _extract():
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()

        # Python AST: precise start/end line extraction
        if file_path.endswith(".py"):
            import ast
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name == symbol_name:
                            start = node.lineno - 1
                            end = node.end_lineno
                            return f"# {file_path} lines {start+1}-{end}\n" + "\n".join(lines[start:end])
            except SyntaxError:
                pass  # Fall through to generic extraction

        # Generic fallback: keyword + exact word boundary detection
        import re
        for i, line in enumerate(lines):
            if re.search(rf"\b(def|class|function|fn|func|struct|impl)\s+{re.escape(symbol_name)}\b", line):
                start = i
                indent = len(line) - len(line.lstrip())
                end = start + 1
                while end < len(lines):
                    stripped = lines[end].strip()
                    if stripped and (len(lines[end]) - len(lines[end].lstrip())) <= indent and not stripped.startswith(("#", "//", "/*", "*", "@")):
                        break
                    end += 1
                return f"# {file_path} lines {start+1}-{end}\n" + "\n".join(lines[start:end])

        return f"Symbol '{symbol_name}' not found in {file_path}"

    try:
        return await asyncio.to_thread(_extract)
    except Exception as e:
        return f"Error reading code block: {e}"

def _write_file(path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {path}"
    except Exception as e:
        return f"Error writing file {path}: {e}"


