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

