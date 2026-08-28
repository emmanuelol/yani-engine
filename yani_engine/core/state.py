from yani_engine.core.locks import _MEMORY_MUTEX, _KNOWLEDGE_MUTEX, _REGISTRY_LOCK, get_registry_lock, _FILE_LOCK
from markdown_it import MarkdownIt
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
        """Locates a markdown heading block using markdown-it-py token parsing.
        Correctly handles code fences, nested blocks, and trailing heading titles.
        Returns (start_line_idx, end_line_idx) or (-1, -1) if not found.
        """
        md = MarkdownIt("commonmark")
        tokens = md.parse(content)
        
        target_tag = f"h{len(header_level)}"  # "##" -> "h2", "###" -> "h3"
        target_title = header_title.lower().strip()
        heading_level = len(header_level)
        
        start_idx = -1
        end_idx = -1
        
        # Phase 1: Find the target heading
        for i, token in enumerate(tokens):
            if token.type == "heading_open" and token.tag == target_tag and token.map:
                if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                    inline_content = tokens[i + 1].content.lower().strip()
                    clean_content = re.sub(r'[*_]{1,2}', '', inline_content).strip()
                    # Match exact title or title with trailing subtitle (e.g. "T-001: Title")
                    if clean_content == target_title or clean_content.startswith(target_title + ":"):
                        start_idx = token.map[0]
                        break
        
        # Phase 2: Find the boundary (next heading at same-or-higher level)
        if start_idx != -1:
            found_start = False
            for token in tokens:
                if token.type == "heading_open" and token.map:
                    if found_start:
                        current_level = int(token.tag[1])
                        if current_level <= heading_level:
                            end_idx = token.map[0]
                            break
                    elif token.map[0] == start_idx:
                        found_start = True
            if end_idx == -1:
                end_idx = len(content.splitlines())
        
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
_TASK_CACHE = None
_CACHE_DIRTY = False

async def update_task_registry_row(task_id: str, new_status: str, new_owner: str = "—", checkpoint_id: str = None) -> str:
    """Surgically updates a task's status in memory, deferred disk flush."""
    global _TASK_CACHE, _CACHE_DIRTY
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            try:
                state = TaskRegistryState()
                
                # HYBRID OPTIMIZATION: Load once, cache indefinitely during execution
                if _TASK_CACHE is None:
                    _TASK_CACHE = state._load_tasks_unlocked()
                
                if task_id not in _TASK_CACHE:
                    return f"Error: Task {task_id} not found."
                
                _TASK_CACHE[task_id]["status"] = new_status
                _TASK_CACHE[task_id]["owner"] = new_owner
                if checkpoint_id:
                    _TASK_CACHE[task_id]["checkpoint"] = checkpoint_id
                
                _CACHE_DIRTY = True
                success_msg = f"Successfully updated {task_id} to {new_status} (Cached)."
                return success_msg
            except Exception as e:
                return f"Error updating registry: {e}"

async def flush_task_registry():
    """Flushes the deferred state cache to disk."""
    global _TASK_CACHE, _CACHE_DIRTY
    if not _CACHE_DIRTY or _TASK_CACHE is None:
        return
        
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            def _sync():
                with _FILE_LOCK:
                    state = TaskRegistryState()
                    state._sync_to_markdown_unlocked(_TASK_CACHE)
            await asyncio.to_thread(_sync)
            _CACHE_DIRTY = False
            print("💾 [STATE] Successfully flushed registry cache to disk.")
        



def _invalidate_task_cache():
    global _TASK_CACHE, _CACHE_DIRTY
    _TASK_CACHE = None
    _CACHE_DIRTY = False

def _atomic_write_memory_unlocked(content: str):
    import os, uuid
    tmp_path = f".yani/tmp/memory_{uuid.uuid4().hex[:6]}.tmp"
    os.makedirs(".yani/tmp", exist_ok=True)
    with _FILE_LOCK:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, "memory.md")

async def _async_atomic_write_memory(content: str):
    await asyncio.to_thread(_atomic_write_memory_unlocked, content)

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
        tmp_dir = ".yani/tmp"
        chk_dir = ".yani/checkpoints"
        bak_dir = ".yani/rollbacks"
        
        # HYBRID OPTIMIZATION: Fast-Path bypass
        has_tmp = os.path.exists(tmp_dir) and bool(os.listdir(tmp_dir))
        has_chk = os.path.exists(chk_dir) and bool(os.listdir(chk_dir))
        has_bak = os.path.exists(bak_dir) and bool(os.listdir(bak_dir))
        
        if not (has_tmp or has_chk or has_bak):
            from yani_engine.core.config import config
            if unattended and getattr(config, 'verbose', False):
                from rich.console import Console
                Console().print("[dim]Orphan recovery scan: clean (fast-path)[/dim]")
            return

        async with _MEMORY_MUTEX:
          async with get_registry_lock():
            
            if unattended:
                from rich.console import Console
                Console().print("[yellow]Unattended mode: Auto-resolving safe orphans, skipping interactive prompts.[/yellow]")
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
                    bak_files = glob.glob(os.path.join(bak_dir, "*", encoded_path))
                    if bak_files:
                        bak_file = bak_files[0]
                        
                if bak_file:
                    if os.path.exists(target) and filecmp.cmp(target, bak_file, shallow=False):
                        new_status = "rolled-back"
                    else:
                        # Escalate to user warning instead of auto-promoting
                        console.print(f"[bold red]WARNING: Task {task_id} modified {target} but was never officially completed. Leaving as 'planned' for manual review.[/bold red]")
                        new_status = "planned"
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
                await _async_atomic_write_memory(new_content)
                _invalidate_task_cache()

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
                            "checkpoint": parts[8],
                            "original_line": line
                        }
                    elif len(parts) >= 5:
                        tasks[parts[1]] = {
                            "id": parts[1],
                            "title": parts[2],
                            "type": parts[3] if len(parts) > 3 else "unknown",
                            "status": parts[4] if len(parts) > 4 else "unknown",
                            "deps": [],
                            "original_line": line
                        }

            # Extract outputs from Task Details block
            det_start, det_end = ASTMemoryMapper.locate_heading_block(content, "##", "Task Details")
            if det_start != -1:
                det_lines = content.splitlines()[det_start:det_end]
                current_task = None
                for line in det_lines:
                    if line.startswith("### "):
                        current_task = line.replace("### ", "").strip()
                    elif current_task and current_task in tasks and "- **Outputs**:" in line:
                        out_str = line.split(":", 1)[1].strip()
                        tasks[current_task]["outputs"] = [o.strip() for o in out_str.split(",") if o.strip()]
            
            # Default empty outputs
            for t_id in tasks:
                if "outputs" not in tasks[t_id]:
                    tasks[t_id]["outputs"] = []
                    
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
            stat_idx, owner_idx, sess_idx, chk_idx = 4, 5, 7, 8
            if header_line:
                headers = [h.strip() for h in header_line.split("|")]
                for idx, h in enumerate(headers):
                    if h == "Status": stat_idx = idx
                    elif h == "Owner": owner_idx = idx
                    elif "Session" in h: sess_idx = idx
                    elif "Checkpoint" in h: chk_idx = idx

            new_block = []
            for line in lines[start_idx+1:end_idx]:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5 and "Task ID" not in parts[1] and not parts[1].strip().startswith("---"):
                    tid = parts[1].strip()
                    if tid in tasks:
                        t_data = tasks[tid]
                        max_req_idx = max(stat_idx, owner_idx, sess_idx, chk_idx)
                        
                        # Pad parts array if malformed without hardcoding length
                        while len(parts) <= max_req_idx + 1:
                            parts.append(" ")
                            
                        parts[stat_idx] = f" {t_data.get('status', 'unknown')} "
                        parts[owner_idx] = f" {t_data.get('owner', '—')} "
                        parts[sess_idx] = f" {t_data.get('session', '—')} "
                        parts[chk_idx] = f" {t_data.get('checkpoint', 'none')} "
                        
                        # Preserve all trailing custom columns
                        if parts[-1].strip() != "":
                            parts.append("")
                        new_block.append("|".join(parts))
                    else:
                        new_block.append(line)
                else:
                    new_block.append(line)
            # --- NEW: Dual-Update for Task Details ---
            det_start, det_end = ASTMemoryMapper.locate_heading_block(content, "##", "Task Details")
            if det_start != -1:
                current_task = None
                import re
                for i in range(det_start + 1, det_end):
                    line = lines[i].strip()
                    
                    # Track which task block we are currently inside
                    if line.startswith("### T-"):
                        match = re.match(r"^###\s+(T-\d{3,4})", line)
                        if match:
                            current_task = match.group(1)
                    
                    # Apply cached updates to the details block
                    if current_task and current_task in tasks:
                        if line.startswith("- **Status**:"):
                            lines[i] = f"- **Status**: {tasks[current_task]['status']}"
                        elif line.startswith("- **Owner**:"):
                            lines[i] = f"- **Owner**: {tasks[current_task]['owner']}"
                        elif line.startswith("- **Checkpoint**:") and 'checkpoint' in tasks[current_task]:
                            lines[i] = f"- **Checkpoint**: {tasks[current_task]['checkpoint']}"
            # -----------------------------------------
                        
            new_content = "\n".join(lines[:start_idx+1] + new_block + lines[end_idx:])
            with open(self.md_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            raise IOError(f"Critical State Error: Failed to sync task registry to memory.md: {e}")



async def read_file(path: str) -> str:
    def _read():
        try:
            expanded_path = os.path.expanduser(path)
            with open(expanded_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except Exception as e:
            return f"Error reading {path}: {e}"
    return await asyncio.to_thread(_read)

async def write_file_with_review(path: str, content: str, task_id: str, **kwargs) -> str:
    """
    CRITICAL: This tool AUTOMATICALLY executes the entire 6-Step Checkpoint Protocol and CodeGraph Impact checks. 
    Do NOT manually create rollbacks, JSON checkpoints, or .tmp files. 
    Simply pass the final target `path` (e.g., 'app/main.py') and the full new `content`.
    """
    try:
        try:
            # Skip impact checks for non-source files to save time
            if not path.endswith(('.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini', '.lock')):
                # Drop timeout to 5s. If it hangs, kill it instantly and fail open.
                impact_proc = await asyncio.to_thread(
                    subprocess.run, 
                    ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "impact", path], 
                    capture_output=True, text=True, check=True, timeout=5
                )
                match = re.search(r"—\s*(\d+)\s+affected symbol", impact_proc.stdout if hasattr(impact_proc, 'stdout') else str(impact_proc))
                if match and int(match.group(1)) > 20:
                    return f"Error: CodeGraph impact threshold exceeded ({match.group(1)} symbols > 20). Write blocked."
        except subprocess.TimeoutExpired:
            return "Error: CodeGraph impact analysis timed out (5s limit). Write blocked (fail-closed)."
        except subprocess.CalledProcessError as e:
            print(f"Warning: CodeGraph impact check failed (exit {e.returncode}). Proceeding with caution.")
        except Exception as e:
            print(f"Warning: CodeGraph impact check failed: {e}. Proceeding with caution.")

        tmp_dir = ".yani/tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        import uuid
        encoded_path = path.replace("/", "__").replace(":", "__colon__")
        tmp_path = os.path.join(tmp_dir, f"{task_id}_{encoded_path}.tmp")
        
        if os.path.exists(tmp_path):
            with open(tmp_path, "w") as f:
                f.write(content)
            return f"Updated existing staged file {path} for review. No new checkpoint created."
        
        import time
        from datetime import datetime
        manager = CheckpointManager()
        chk_id = f"chk_{time.time_ns()}_{uuid.uuid4().hex[:6]}"
        
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
        rollback_path = os.path.join(".yani", "rollbacks", task_id, encoded_path)
        checkpoint_path = os.path.join(".yani", "checkpoints", f"{chk_id}.json")
        
        await manager.write_rollback_copy(path, rollback_path)
        await manager.log_planned_change(path, metadata)
        await manager.write_checkpoint_json(checkpoint_path, metadata)
        
        # Link checkpoint to the task in the Task Registry
        reg_success = await update_task_registry_row(task_id, "in_progress", checkpoint_id=chk_id)
        if not reg_success:
            return f"Error: Task {task_id} not found in the Task Registry. File not staged."
        
        with open(tmp_path, "w") as f:
            f.write(content)
            
        # REMOVED: Direct write to target. File is staged in tmp_path only.
        # Target `path` is written ONLY upon Diff-Gate approval via
        # CheckpointManager.atomic_rename_to_target() in orchestrator.py.
            
        # NEW: Only execute shadow sync if utilizing isolated containers
        sandbox_mode = kwargs.get("sandbox_mode", "yani-base")
        if sandbox_mode not in ["native"] and not sandbox_mode.startswith("compose:"):
            shadow_path = os.path.join(f".yani/shadow_{task_id}", path)
            if os.path.exists(f".yani/shadow_{task_id}"):
                os.makedirs(os.path.dirname(os.path.abspath(shadow_path)), exist_ok=True)
                with open(shadow_path, "w") as f:
                    f.write(content)
            
        return f"Changes staged for review at {tmp_path} (Rollback: {rollback_path}). File will be applied upon Diff-Gate approval."
    except Exception as e:
        return f"Error in write_file_with_review for {path}: {e}"

async def register_task_batch(tasks: list[dict]) -> str:
    """Registers a batch of atomic tasks to the memory.md Task Registry safely and atomically.
    
    CRITICAL: The 'tasks' array MUST contain dictionaries with EXACTLY these keys:
    - 'title' (str)
    - 'task_type' (str: 'change', 'analysis', 'validation')
    - 'deps' (str: comma-separated IDs like 'T-001' or 'none')
    - 'description' (str: detailed explanation)
    - 'outputs' (str: comma-separated file paths)
    - 'success_criteria' (str: concrete evaluation metric)
    - 'estimated_effort' (str: 'small', 'medium', 'large')
    - 'codegraph_impact' (str: blast radius summary)
    """
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            try:
                with open("memory.md", "r", encoding="utf-8") as f:
                    content = f.read()
                
                reg_start, reg_end = ASTMemoryMapper.locate_heading_block(content, "##", "Task Registry")
                arc_start, arc_end = ASTMemoryMapper.locate_heading_block(content, "##", "Archive Index")
                
                search_blocks = ""
                if reg_start != -1 and reg_end != -1:
                    search_blocks += "\n".join(content.splitlines()[reg_start:reg_end])
                if arc_start != -1 and arc_end != -1:
                    search_blocks += "\n".join(content.splitlines()[arc_start:arc_end])
                
                import re
                existing_ids = re.findall(r'T-(\d{3,4})', search_blocks)
                next_num = max([int(x) for x in existing_ids]) + 1 if existing_ids else 1
                
                existing_task_ids = set([f"T-{int(x):03d}" for x in existing_ids])
                incoming_task_ids = [f"T-{next_num + i:03d}" for i in range(len(tasks))]
                union_task_ids = existing_task_ids.union(incoming_task_ids)
                
                det_start, det_end = ASTMemoryMapper.locate_heading_block(content, "##", "Task Details")
                
                if det_start == -1 or reg_start == -1:
                    return "Error: Header '## Task Registry' or '## Task Details' not found in memory.md"
                    
                lines = content.splitlines()
                
                rows_to_insert = []
                details_to_insert = []
                
                for i, task in enumerate(tasks):
                    task_id = incoming_task_ids[i]
                    title = task.get("title", "Untitled")
                    outputs = task.get("outputs", "none")
                    
                    # ENFORCE CATEGORIZATION (SOFT WARNING)
                    if not title.startswith("[") or "]" not in title:
                        print(f"⚠️ [ARCHITECT WARNING] Task '{title}' missing [Category] tag. Auto-patching to conserve tokens.")
                        title = f"[Uncategorized] {title}"
                        task["title"] = title

                    # ENFORCE ATOMICITY (SOFT WARNING)
                    if outputs.lower() not in ["none", "—", "-", ""]:
                        output_files = [o.strip() for o in outputs.split(",")]
                        if len(output_files) > 2 and task.get("estimated_effort", "small") == "small":
                            print(f"⚠️ [ARCHITECT WARNING] Task '{title}' assigned {len(output_files)} files to a 'small' effort tier. (Registered as-is to save tokens; consider splitting manually later).")

                    task_type = task.get("task_type", "change")
                    deps = task.get("deps", "none")
                    description = task.get("description", "")
                    success_criteria = task.get("success_criteria", "TBD")
                    estimated_effort = task.get("estimated_effort", "small")
                    codegraph_impact = task.get("codegraph_impact", "—")
                    
                    if deps.lower() not in ["none", "—", "-", ""]:
                        for d in [d.strip() for d in deps.split(",")]:
                            if d not in union_task_ids:
                                return f"Error: Dependency {d} does not exist in registry or current batch. Task batch creation rejected."

                    rows_to_insert.append(f"| {task_id} | {title} | {task_type} | pending | — | {deps} | — | none |")
                    details_to_insert.append(f"\n### {task_id}: {title}\n- **Type**: {task_type}\n- **Status**: pending\n- **Owner**: —\n- **Depends On**: {deps}\n- **Assigned Session**: —\n- **Description**: {description}\n- **Inputs**: none\n- **Outputs**: {outputs}\n- **Success Criteria**: {success_criteria}\n- **Estimated Effort**: {estimated_effort}\n- **Parallelizable**: yes\n- **CodeGraph Impact**: {codegraph_impact}\n- **Checkpoint**: none\n- **Resume Instructions**: none\n- **Notes**: —\n")

                lines = lines[:det_end] + details_to_insert + lines[det_end:]
                
                reg_start_new, reg_end_new = ASTMemoryMapper.locate_heading_block("\n".join(lines), "##", "Task Registry")
                
                reg_insert = reg_end_new
                for i in range(reg_end_new - 1, reg_start_new, -1):
                    if lines[i].strip():
                        reg_insert = i + 1
                        break
                
                lines = lines[:reg_insert] + rows_to_insert + lines[reg_insert:]

                await _async_atomic_write_memory("\n".join(lines) + "\n")
                _invalidate_task_cache()
                    
                success_msg = f"Successfully registered tasks {', '.join(incoming_task_ids)}."
                print(f"💾 [STATE] {success_msg}")
                return success_msg
            except Exception as e:
                error_msg = f"Error adding task batch: {e}"
                print(f"❌ [STATE ERROR] {error_msg}")
                return error_msg

async def add_task(title: str, task_type: str = "change", deps: str = "none", description: str = "", outputs: str = "none", success_criteria: str = "TBD", estimated_effort: str = "small", codegraph_impact: str = "—") -> str:
    """DEPRECATED. Use register_task_batch instead. Registers a new atomic task to the memory.md Task Registry."""
    return await register_task_batch([{
        "title": title, "task_type": task_type, "deps": deps, "description": description,
        "outputs": outputs, "success_criteria": success_criteria, "estimated_effort": estimated_effort,
        "codegraph_impact": codegraph_impact
    }])
    

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
                        import asyncio
                        try:
                            await asyncio.to_thread(subprocess.run, [sys.executable, "sync_knowledge.py"], capture_output=True, timeout=10)
                        except subprocess.TimeoutExpired:
                            print("Warning: sync_knowledge.py timed out after 10s")

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
                await _async_atomic_write_memory(content)
                _invalidate_task_cache()

async def append_session_log_row(session_id: str, task_id: str) -> str:
    """Appends a new tracking row to the Session Log table in memory.md."""
    from datetime import datetime
    start_time = datetime.now().isoformat()
    row = f"| {session_id} | {start_time} | — | {task_id} | in_progress | — |"
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            def _append():
                with _FILE_LOCK:
                    ASTMemoryMapper.append_to_markdown_table("memory.md", "Session Log", row)
            await asyncio.to_thread(_append)
    return f"Session {session_id} logged for task {task_id}."


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


