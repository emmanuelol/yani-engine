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
            container_name = f"dumbledoer-sandbox-{project_hash}-{worker_id}"
            
            # Check if already running
            chk = subprocess.run(["docker", "ps", "-q", "-f", f"name={container_name}"], capture_output=True, text=True)
            if chk.stdout.strip():
                return True
                
            # Create Shadow Clone
            shadow_dir = os.path.abspath(f".dumbledoer/shadow_{worker_id}")
            if os.path.exists(shadow_dir):
                shutil.rmtree(shadow_dir)
            os.makedirs(shadow_dir, exist_ok=True)
            
            # Optimized Shadow Clone using OS Hard Links (near-instant, no byte copies)
            ignore_patterns = shutil.ignore_patterns(
                ".git", ".venv", "venv", "env", ".pytest_cache", "__pycache__", 
                "node_modules", ".dumbledoer", ".codegraph", "*.tmp", "*.bak", "shadow_*"
            )
            try:
                shutil.copytree(os.getcwd(), shadow_dir, ignore=ignore_patterns, copy_function=os.link, dirs_exist_ok=True)
            except OSError:
                # Fallback to regular copy if hard links not supported (e.g., cross-filesystem)
                shutil.copytree(os.getcwd(), shadow_dir, ignore=ignore_patterns, dirs_exist_ok=True)
            
            # --- NEW: Dynamic Target Image Resolution ---
            target_image = "dumbledoer-base:latest"
            
            if sandbox_mode.startswith("docker:"):
                target_image = sandbox_mode.split(":")[1]
            elif sandbox_mode == "auto":
                if os.path.exists(os.path.join(shadow_dir, "Dockerfile")):
                    target_image = f"dumbledoer-custom-{project_hash}"
                    print(f"Building native sandbox from project Dockerfile: {target_image}...")
                    subprocess.run(["docker", "build", "-t", target_image, "."], cwd=shadow_dir, capture_output=True, check=True)
            
            sandbox_proc = subprocess.Popen(
                ["docker", "run", "--rm", "-i", 
                 "--memory=1500m", "--memory-swap=1500m",  # Strict RAM cap
                 "--name", container_name,
                 "-v", f"{shadow_dir}:/workspace", "-w", "/workspace", 
                 target_image, "/bin/bash"],
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

async def _teardown_warm_sandbox(task_id: str = None, worker_id: str = None):
    active_id = worker_id or task_id
    if not active_id: return
    def _do_teardown():
        try:
            import hashlib
            project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
            container_name = f"dumbledoer-sandbox-{project_hash}-{worker_id}"
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            shadow_dir = os.path.abspath(f".dumbledoer/shadow_{worker_id}")
            if os.path.exists(shadow_dir):
                shutil.rmtree(shadow_dir)
        except Exception:
            pass
    await asyncio.to_thread(_do_teardown)

import atexit
import glob

def _cleanup_all_sandboxes():
    try:
        # stop all running dumbledoer-sandbox containers
        res = subprocess.run(["docker", "ps", "-q", "-f", "name=dumbledoer-sandbox-"], capture_output=True, text=True)
        if res.stdout.strip():
            for cid in res.stdout.strip().splitlines():
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
        # remove all shadow dirs
        for shadow_dir in glob.glob(".dumbledoer/shadow_*"):
            shutil.rmtree(shadow_dir, ignore_errors=True)
    except Exception:
        pass

atexit.register(_cleanup_all_sandboxes)

async def execute_bash(command: str, sandbox_mode: str = "dumbledoer-base", task_id: str = None, worker_id: str = None) -> str:
    def _run():
        try:
            import shlex
            safe_command = shlex.quote(command)
            
            # NEW: Dynamically resolve the workspace path based on execution context
            work_dir = os.getcwd() if sandbox_mode == "native" else "/workspace"
            env_wrapper = f"export PYTHONPATH={work_dir}:$PYTHONPATH && {safe_command}"
            
            # --- APPLY FIX 3: Secure Native Sandbox Execution ---
            if sandbox_mode == "native":
                result = subprocess.run(["bash", "-c", env_wrapper],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                
            # --- NEW: Docker Compose Integration ---
            elif sandbox_mode and sandbox_mode.startswith("compose:"):
                service_name = sandbox_mode.split(":")[1]
                result = subprocess.run(
                    ["docker", "compose", "exec", "-T", service_name, "/bin/bash", "-c", env_wrapper],
                    capture_output=True, text=True, timeout=300
                )
                return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

            # --- UPDATED: Fallback parsing for 'auto' and 'docker:<image>' ---
            else:
                image = "dumbledoer-base:latest"
                if sandbox_mode and sandbox_mode.startswith("docker:"):
                    image = sandbox_mode.split(":")[1]
                elif sandbox_mode == "auto" and os.path.exists("Dockerfile"):
                    image = "dumbledoer-custom-fallback"
                    subprocess.run(["docker", "build", "-t", image, "."], capture_output=True)

                active_id = worker_id or task_id
                if active_id and _is_sandbox_warm_sync(active_id):
                    import hashlib
                    project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
                    container_name = f"dumbledoer-sandbox-{project_hash}-{active_id}"
                    
                    result = subprocess.run(
                        ["docker", "exec", "-i", container_name, "/bin/bash", "-c", env_wrapper],
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                else:
                    # Mount as read-write (:rw) so discovery commands (pip install, touch) work.
                    # Extended timeout (300s) to support heavy installs.
                    result = subprocess.run(
                        ["docker", "run", "--rm", "-i", 
                         "--memory=1500m", "--memory-swap=1500m",
                         "-v", f"{os.getcwd()}:/workspace:rw", "-w", "/workspace", 
                         image, "/bin/bash", "-c", env_wrapper],
                        capture_output=True,
                        text=True,
                        timeout=300
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

