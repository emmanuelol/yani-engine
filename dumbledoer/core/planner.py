import ast
import os
from dumbledoer.core.state import TaskRegistryState

class WavePlanner:
    def __init__(self, start_at_index: int = 0):
        self.start_at_index = start_at_index

    def _files_are_import_coupled(self, file_a: str, file_b: str) -> bool:
        """Check if file_a imports file_b or vice versa using CodeGraph impact (transitive) or Python AST."""
        import subprocess
        
        # --- APPLY FIX 3: Transitive coupling via CodeGraph ---
        if os.path.exists(".codegraph"):
            try:
                # Check if modifying file_a impacts file_b
                res_a = subprocess.run(["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "impact", file_a], capture_output=True, text=True, timeout=5)
                if file_b in res_a.stdout: return True
                
                # Check if modifying file_b impacts file_a
                res_b = subprocess.run(["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "impact", file_b], capture_output=True, text=True, timeout=5)
                if file_a in res_b.stdout: return True
                
                return False # Clean pass
            except Exception:
                pass # Silent fallback to shallow AST if CodeGraph is busy/offline

        # Fallback shallow AST logic
        try:
            for src, target in [(file_a, file_b), (file_b, file_a)]:
                if not os.path.exists(src) or not src.endswith(".py"):
                    continue
                with open(src, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                # Derive module name from file path
                target_module = os.path.splitext(os.path.basename(target))[0]
                target_dotpath = target.replace("/", ".").replace(".py", "")
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if target_module in alias.name or target_dotpath in alias.name:
                                return True
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and (target_module in node.module or target_dotpath in node.module):
                            return True
            return False
        except Exception:
            return False  # Fail open: don't block parallelism on parse errors

    async def get_pending_waves(self) -> list[list[dict]]:
        state = TaskRegistryState()
        tasks_dict = await state.load_tasks()
        tasks = list(tasks_dict.values())
        
        # Apply the explicit bounding index constraint
        import re

        pending_tasks = {
            t['id']: t for t in tasks 
            if "pending" in t['status'] 
            and int(re.search(r'\d+', t['id']).group()) >= self.start_at_index
        }
        completed_task_ids = {t['id'] for t in tasks if "completed" in t['status']}
        
        waves = []
        while pending_tasks:
            current_wave = []
            claimed_files_in_wave = set()
            
            for t_id, t in list(pending_tasks.items()):
                if all(d in completed_task_ids for d in t['deps']):
                    task_files = set(t.get('outputs', []))

                    # [SEMANTIC DEPENDENCY CHECK] Detect import coupling between task outputs
                    import_coupled = False
                    for claimed_file in claimed_files_in_wave:
                        for task_file in task_files:
                            if self._files_are_import_coupled(claimed_file, task_file):
                                import_coupled = True
                                break
                        if import_coupled:
                            break

                    if not task_files or (not task_files.intersection(claimed_files_in_wave) and not import_coupled):
                        current_wave.append(t)
                        claimed_files_in_wave.update(task_files)
                        
            if not current_wave:
                if pending_tasks:
                    blocked = []
                    for t_id, t in pending_tasks.items():
                        unfulfilled = [d for d in t['deps'] if d not in completed_task_ids]
                        blocked.append(f"{t_id} (missing: {', '.join(unfulfilled)})")
                    print(f"Warning: Cannot schedule remaining pending tasks. They are blocked by uncompleted dependencies: {'; '.join(blocked)}")
                    break
                
            waves.append(current_wave)
            for t in current_wave:
                del pending_tasks[t['id']]
                completed_task_ids.add(t['id'])
                
        return waves
