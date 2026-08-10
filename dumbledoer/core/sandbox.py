from dumbledoer.core.locks import _MEMORY_MUTEX, _REGISTRY_LOCK, get_registry_lock
import os
import sys
import asyncio
import subprocess
import shutil


def _is_sandbox_warm_sync(task_id: str) -> bool:
    try:
        import hashlib
        project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
        result = subprocess.run(["docker", "ps", "-q", "-f", f"name=dumbledoer-sandbox-{project_hash}-{task_id}"], capture_output=True, text=True)
        return bool(result.stdout.strip())
    except Exception:
        return False

async def _ensure_warm_sandbox(task_id: str = None, image: str = "dumbledoer-base:latest") -> bool:
    if not task_id: return False
    
    def _do_warm():
        try:
            import hashlib
            project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
            container_name = f"dumbledoer-sandbox-{project_hash}-{task_id}"
            
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
            ignore_patterns = shutil.ignore_patterns(".git", ".venv", "venv", "env", ".pytest_cache", "__pycache__", "node_modules", ".dumbledoer", ".codegraph")
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
            import hashlib
            project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
            container_name = f"dumbledoer-sandbox-{project_hash}-{task_id}"
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            shadow_dir = os.path.abspath(f".dumbledoer/shadow_{task_id}")
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
                    import hashlib
                    project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
                    container_name = f"dumbledoer-sandbox-{project_hash}-{task_id}"
                    result = subprocess.run(
                        ["docker", "exec", "-i", container_name, "/bin/bash", "-c", command],
                        capture_output=True,
                        text=True,
                        timeout=120
                    )
                    return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                else:
                    result = subprocess.run(
                        ["docker", "run", "--rm", "-i", "-v", f"{os.getcwd()}:/workspace:ro", "-w", "/workspace", image, "/bin/bash", "-c", command],
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

