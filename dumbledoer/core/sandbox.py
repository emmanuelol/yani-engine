import os
import sys
import asyncio
import subprocess
import shutil


def _is_sandbox_warm_sync(task_id: str) -> bool:
    try:
        result = subprocess.run(["docker", "ps", "-q", "-f", f"name=dumbledoer-sandbox-{task_id}"], capture_output=True, text=True)
        return bool(result.stdout.strip())
    except Exception:
        return False

async def _ensure_warm_sandbox(task_id: str = None, image: str = "dumbledoer-base:latest") -> bool:
    if not task_id: return False
    
    def _do_warm():
        try:
            container_name = f"dumbledoer-sandbox-{task_id}"
            
            # Check if already running
            chk = subprocess.run(["docker", "ps", "-q", "-f", f"name={container_name}"], capture_output=True, text=True)
            if chk.stdout.strip():
                return True
                
            # Create Shadow Clone
            shadow_dir = os.path.abspath(f".dumbledoer/shadow_{task_id}")
            if os.path.exists(shadow_dir):
                shutil.rmtree(shadow_dir)
            os.makedirs(shadow_dir, exist_ok=True)
            
            # Native Python shadow clone
            ignore_patterns = shutil.ignore_patterns(".git", ".venv", ".pytest_cache", "__pycache__", "node_modules")
            shutil.copytree(os.getcwd(), shadow_dir, ignore=ignore_patterns, dirs_exist_ok=True)
            
            sandbox_proc = subprocess.Popen(
                ["docker", "run", "--rm", "-i", "--name", container_name,
                "-v", f"{shadow_dir}:/workspace", "-w", "/workspace", image, "/bin/bash"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Verify it started
            import time
            time.sleep(0.5)
            chk2 = subprocess.run(["docker", "ps", "-q", "-f", f"name={container_name}"], capture_output=True, text=True)
            return bool(chk2.stdout.strip())
        except Exception as e:
            raise RuntimeError(f"Docker infrastructure failure. Is the daemon running? Details: {e}")
    return await asyncio.to_thread(_do_warm)

async def _teardown_warm_sandbox(task_id: str = None):
    if not task_id: return
    def _do_teardown():
        try:
            container_name = f"dumbledoer-sandbox-{task_id}"
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            shadow_dir = os.path.abspath(f".dumbledoer/shadow_{task_id}")
            if os.path.exists(shadow_dir):
                shutil.rmtree(shadow_dir)
        except Exception:
            pass
    await asyncio.to_thread(_do_teardown)

async def execute_bash(command: str, sandbox_mode: str = None, task_id: str = None) -> str:
    def _run():
        try:
            if sandbox_mode == "native":
                result = subprocess.run(["bash", "-c", command],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            else:
                image = "dumbledoer-base:latest" if sandbox_mode == "dumbledoer-base" else "ubuntu:latest"
                if task_id and _is_sandbox_warm_sync(task_id):
                    container_name = f"dumbledoer-sandbox-{task_id}"
                    result = subprocess.run(
                        ["docker", "exec", "-i", container_name, "/bin/bash", "-c", command],
                        capture_output=True,
                        text=True,
                        timeout=120
                    )
                    return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                else:
                    result = subprocess.run(
                        ["docker", "run", "--rm", "-i", image, "/bin/bash", "-c", command],
                        capture_output=True,
                        text=True,
                        timeout=120
                    )
                    return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 120 seconds"
        except Exception as e:
            return f"Error executing bash: {str(e)}"
    return await asyncio.to_thread(_run)

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
            return self._load_tasks_unlocked()

    def _load_tasks_unlocked(self) -> dict:
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
                        deps_str = parts[dep_idx].strip() if len(parts) > dep_idx else ""
                        deps = [d.strip() for d in deps_str.split(",") if "T-" in d and d.strip() != task_id]

                        tasks[task_id] = {
                            "id": task_id,
                            "desc": description,
                            "title": parts[title_idx].strip() if len(parts) > title_idx else task_id,
                            "status": status_col,
                            "deps": deps,
                            "outputs": target_files,
                            "original_line": line
                        }
        except Exception as e:
            print(f"Warning: Failed to load tasks from memory.md: {e}", file=sys.stderr)
        return tasks

    def save_tasks(self, tasks: dict):
        self._sync_to_markdown(tasks)
        
    