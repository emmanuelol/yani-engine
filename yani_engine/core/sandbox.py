from yani_engine.core.locks import _MEMORY_MUTEX, _REGISTRY_LOCK, get_registry_lock
import os
import sys
import asyncio
import subprocess
import shutil
import shlex
import signal


def _is_sandbox_warm_sync(worker_id: str) -> bool:
    try:
        import hashlib
        project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
        # Added timeout to prevent sync blocking if Docker daemon hangs
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name=yani-sandbox-{project_hash}-{worker_id}"], 
            capture_output=True, text=True, timeout=5
        )
        return bool(result.stdout.strip())
    except Exception:
        return False

# TASK 1: Async Sandbox State Resolver
async def _is_sandbox_warm(worker_id: str) -> bool:
    """Non-blocking validation of active container state to prevent event loop starvation."""
    return await asyncio.to_thread(_is_sandbox_warm_sync, worker_id)

async def _ensure_warm_sandbox(task_id: str = None, worker_id: str = None, sandbox_mode: str = "yani-base") -> bool:
    active_id = worker_id or task_id
    if not active_id: return False
    
    def _do_warm():
        try:
            import hashlib
            project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
            container_name = f"yani-sandbox-{project_hash}-{active_id}"
            
            # Check if already running
            chk = subprocess.run(["docker", "ps", "-q", "-f", f"name={container_name}"], capture_output=True, text=True)
            if chk.stdout.strip():
                return True
                
            # Ruthlessly purge any exited or crashed containers holding the target name
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)
                
            # Create Shadow Worktree / Clone Atomically
            shadow_dir = os.path.abspath(f".yani/shadow_{active_id}")
            branch_name = f"yani-worker-{active_id}"

            if os.path.exists(shadow_dir):
                subprocess.run(["git", "worktree", "remove", "--force", shadow_dir], capture_output=True, check=False)
                shutil.rmtree(shadow_dir, ignore_errors=True)
            subprocess.run(["git", "branch", "-D", branch_name], capture_output=True, check=False)
            subprocess.run(["git", "worktree", "prune"], capture_output=True, check=False)

            is_git_repo = False
            try:
                chk_git = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=False)
                is_git_repo = (chk_git.returncode == 0 and chk_git.stdout.strip() == "true")
            except Exception:
                is_git_repo = False

            if is_git_repo:
                os.makedirs(".yani", exist_ok=True)
                wt_res = subprocess.run(
                    ["git", "worktree", "add", "-b", branch_name, shadow_dir, "HEAD"],
                    capture_output=True, text=True, check=False
                )
                if wt_res.returncode != 0:
                    os.makedirs(shadow_dir, exist_ok=True)
                    ignore_patterns = shutil.ignore_patterns(
                        ".git", ".venv", "venv", "env", ".pytest_cache", "__pycache__", 
                        "node_modules", ".yani", ".codegraph", "*.tmp", "*.bak", "shadow_*"
                    )
                    shutil.copytree(os.getcwd(), shadow_dir, ignore=ignore_patterns, dirs_exist_ok=True)
            else:
                os.makedirs(shadow_dir, exist_ok=True)
                ignore_patterns = shutil.ignore_patterns(
                    ".git", ".venv", "venv", "env", ".pytest_cache", "__pycache__", 
                    "node_modules", ".yani", ".codegraph", "*.tmp", "*.bak", "shadow_*"
                )
                shutil.copytree(os.getcwd(), shadow_dir, ignore=ignore_patterns, dirs_exist_ok=True)
            
            # Dynamic Target Image Resolution
            target_image = "yani-base:latest"
            
            if sandbox_mode.startswith("docker:"):
                target_image = sandbox_mode.split(":")[1]
            elif sandbox_mode == "auto":
                if os.path.exists(os.path.join(shadow_dir, "Dockerfile")):
                    target_image = f"yani-custom-{project_hash}"
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
            container_name = f"yani-sandbox-{project_hash}-{active_id}"
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            shadow_dir = os.path.abspath(f".yani/shadow_{active_id}")
            branch_name = f"yani-worker-{active_id}"
            subprocess.run(["git", "worktree", "remove", "--force", shadow_dir], capture_output=True, check=False)
            subprocess.run(["git", "branch", "-D", branch_name], capture_output=True, check=False)
            if os.path.exists(shadow_dir):
                shutil.rmtree(shadow_dir, ignore_errors=True)
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
        res = subprocess.run(["docker", "ps", "-q", "-f", f"name=yani-sandbox-{project_hash}-"], capture_output=True, text=True, timeout=10)
        if res.stdout.strip():
            for cid in res.stdout.strip().splitlines():
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=10)
        subprocess.run(["git", "worktree", "prune"], capture_output=True, timeout=10, check=False)
        for shadow_dir in glob.glob(".yani/shadow_*"):
            subprocess.run(["git", "worktree", "remove", "--force", shadow_dir], capture_output=True, check=False)
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
        # TASK 2: Launch process with process group isolation (start_new_session)
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,
            start_new_session=True
        )
    except Exception as e:
        return f"Error initiating subprocess: {str(e)}"

    async def _drain_stream(stream, stream_name: str) -> tuple[str, bool]:
        output = bytearray()
        truncated = False
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            
            if len(output) + len(chunk) > max_bytes:
                output.extend(chunk[:(max_bytes - len(output))])
                truncated = True
                break
                
            output.extend(chunk)
            
        return output.decode('utf-8', errors='replace'), truncated

    stdout_task = asyncio.create_task(_drain_stream(process.stdout, 'stdout'))
    stderr_task = asyncio.create_task(_drain_stream(process.stderr, 'stderr'))

    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
        
        stdout_text, stdout_trunc = await stdout_task
        stderr_text, stderr_trunc = await stderr_task
        
        res = f"STDOUT:\n{stdout_text}"
        if stdout_trunc:
            res += f"\n... [SYSTEM OVERRIDE: {max_bytes} byte limit reached. Truncated.]"
            
        res += f"\nSTDERR:\n{stderr_text}"
        if stderr_trunc:
            res += f"\n... [SYSTEM OVERRIDE: {max_bytes} byte limit reached. Truncated.]"
            
        return res

    except asyncio.TimeoutError:
        # TASK 2: Ruthless termination of the entire Process Group to stop orphan leaks
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except ProcessLookupError:
                pass
        return f"CRITICAL: Command timed out after {timeout} seconds and was forcefully killed (SIGKILL)."
        
    finally:
        if not stdout_task.done(): stdout_task.cancel()
        if not stderr_task.done(): stderr_task.cancel()

async def execute_bash(command: str, sandbox_mode: str = "yani-base", task_id: str = None, worker_id: str = None) -> str:
    work_dir = os.getcwd() if sandbox_mode == "native" else "/workspace"
    env_wrapper = f"export PYTHONPATH={work_dir}:$PYTHONPATH && {command}"
    
    user_map = f"{os.getuid()}:{os.getgid()}"
    
    if sandbox_mode == "native":
        return await _safe_async_execute(["bash", "-c", env_wrapper], timeout=120)
        
    elif sandbox_mode and sandbox_mode.startswith("compose:"):
        service_name = sandbox_mode.split(":")[1]
        return await _safe_async_execute(
            ["docker", "compose", "exec", "-T", "--user", user_map, service_name, "/bin/bash", "-c", env_wrapper],
            timeout=300
        )

    else:
        image = "yani-base:latest"
        if sandbox_mode and sandbox_mode.startswith("docker:"):
            image = sandbox_mode.split(":")[1]
        elif sandbox_mode == "auto" and os.path.exists("Dockerfile"):
            image = "yani-custom-fallback"
            await asyncio.to_thread(subprocess.run, ["docker", "build", "-t", image, "."], check=True, capture_output=True, text=True)

        active_id = worker_id or task_id
        
        # TASK 1: Implement non-blocking state check for active container status
        if active_id and await _is_sandbox_warm(active_id):
            import hashlib
            project_hash = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
            container_name = f"yani-sandbox-{project_hash}-{active_id}"
            
            return await _safe_async_execute(
                ["docker", "exec", "--user", user_map, container_name, "/bin/bash", "-c", env_wrapper],
                timeout=300
            )
        else:
            import uuid
            ephemeral_dir = os.path.abspath(f".yani/ephemeral_{uuid.uuid4().hex[:8]}")
            ignore_patterns = shutil.ignore_patterns(
                ".git", ".venv", "venv", "env", ".pytest_cache", "__pycache__", 
                "node_modules", ".yani", ".codegraph", "*.tmp", "*.bak", "shadow_*"
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
                # TASK 3: Escalated Ephemeral Directory Cleanup
                if os.path.exists(ephemeral_dir):
                    try:
                        shutil.rmtree(ephemeral_dir)
                    except Exception:
                        # Fallback: Root-level purge via disposable Alpine container
                        try:
                            await asyncio.shield(_safe_async_execute([
                                "docker", "run", "--rm", 
                                "-v", f"{ephemeral_dir}:/tmp/workspace", 
                                "alpine", "rm", "-rf", "/tmp/workspace"
                            ], timeout=30))
                        except Exception:
                            pass
                        # Final garbage collection attempt
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
            return "Error: RTK binary not found in standard paths."

    # TASK 4: Safe Lexical Parsing for malformed LLM commands
    try:
        args = [rtk_bin] + shlex.split(command)
    except ValueError as e:
        return f"Error parsing command: {e}. Please ensure all quotes are matched and closed."

    try:
        result = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error ({e.returncode}):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
    except Exception as e:
        return f"Exception executing rtk command: {e}"
