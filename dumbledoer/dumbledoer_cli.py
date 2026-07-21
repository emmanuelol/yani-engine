import os
import sys
import asyncio
import argparse
import subprocess
import shlex
from contextlib import AsyncExitStack
import shutil
import difflib
from filelock import FileLock

REGISTRY_LOCK = FileLock("memory.md.lock", timeout=10)

GUI_DIFF_ENABLED = True

from google import genai
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

class PlanValidator:
    pass

class BudgetExhaustedException(Exception):
    pass

class BudgetManager:
    def __init__(self, config_text: str):
        self.estimated_tokens = 0
        self.threshold = 100000
        for line in config_text.splitlines():
            line = line.strip()
            if line.startswith("- budget_limit:"):
                try:
                    self.threshold = int(line.split(":")[1].strip())
                except ValueError:
                    pass
                    
    def check_and_harvest(self):
        if self.estimated_tokens > self.threshold:
            raise BudgetExhaustedException("Budget exhausted")

class ASTMemoryMapper:
    @staticmethod
    def locate_heading_block(content: str, heading_level: str, title: str) -> tuple[int, int]:
        lines = content.splitlines()
        start_idx = -1
        end_idx = -1
        target = f"{heading_level} {title}"
        for i, line in enumerate(lines):
            if line.strip() == target:
                start_idx = i
                break
        if start_idx != -1:
            end_idx = len(lines)
            for j in range(start_idx + 1, len(lines)):
                if lines[j].startswith("#"):
                    end_idx = j
                    break
        return start_idx, end_idx

def execute_bash(command: str, sandbox_mode: str = None) -> str:
    if sandbox_mode is None:
        sandbox_mode = "dumbledoer-base"
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("- sandbox_mode:"):
                        sandbox_mode = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

    try:
        if sandbox_mode == "docker-compose":
            args = ["docker", "compose", "exec", "-T", "app", "bash", "-c", command]
        elif sandbox_mode == "native":
            args = ["docker", "run", "--rm", "-v", f"{os.getcwd()}:/workspace", "-w", "/workspace", "target-repo-img", "bash", "-c", command]
        else:
            args = ["docker", "run", "--rm", "-v", f"{os.getcwd()}:/workspace", "-w", "/workspace", "dumbledoer-base:latest", "bash", "-c", command]
            
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error ({e.returncode}):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
    except Exception as e:
        return f"Exception executing command: {e}"

def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
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

def update_memory_registry(content: str) -> str:
    if "- sandbox_mode:" not in content:
        return "Error updating memory registry: Constraint failed, missing '- sandbox_mode:' in Config block."
    try:
        with REGISTRY_LOCK:
            return _write_file("memory.md", content)
    except Exception as e:
        return f"Error updating memory registry: {e}"

def run_rtk(command: str) -> str:
    try:
        args = ["rtk"] + shlex.split(command)
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error ({e.returncode}):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
    except Exception as e:
        return f"Exception executing rtk command: {e}"

async def write_file_with_review(path: str, content: str) -> str:
    """Writes content to a file via a VS Code Diff-Gate for user approval."""
    try:
        tmp_dir = ".dumbledoer/tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        filename = os.path.basename(path)
        tmp_path = os.path.join(tmp_dir, f"{filename}.tmp")
        
        with open(tmp_path, "w") as f:
            f.write(content)
            
        has_code = shutil.which("code") is not None

        if GUI_DIFF_ENABLED and has_code:
            if os.path.exists(path):
                subprocess.run(["code", "--wait", "--diff", path, tmp_path], check=True)
            else:
                subprocess.run(["code", "--wait", tmp_path], check=True)
            print(f"Review proposed changes for {path} in VS Code.", file=sys.stderr)
        else:
            if os.path.exists(path):
                with open(path, "r") as f:
                    old_content = f.readlines()
                new_content = content.splitlines(keepends=True)
                diff = "".join(difflib.unified_diff(old_content, new_content, fromfile=path, tofile=tmp_path))
                if diff:
                    from rich.console import Console
                    from rich.syntax import Syntax
                    console = Console()
                    console.print(Syntax(diff, "diff", theme="monokai"))
            else:
                print(f"Creating new file {path}. Content preview:\n{content}")
            
        from rich.prompt import Confirm
        approval = await asyncio.to_thread(Confirm.ask, f"Approve changes to {path}?")
        if approval:
            os.replace(tmp_path, path)
            return f"Successfully wrote to {path} (Approved by user)"
        else:
            return f"Error: Changes to {path} were rejected by the user."
    except Exception as e:
        return f"Error in write_file_with_review for {path}: {e}"

class CheckpointManager:
    def write_rollback_copy(self, target_path: str, rollback_path: str):
        if os.path.exists(rollback_path):
            return
        if os.path.exists(target_path):
            os.makedirs(os.path.dirname(rollback_path), exist_ok=True)
            shutil.copy2(target_path, rollback_path)
            
    def log_planned_change(self, target_path: str, metadata: dict):
        pass
        
    def write_checkpoint_json(self, checkpoint_path: str, metadata: dict):
        os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
        with open(checkpoint_path, "w") as f:
            import json
            json.dump(metadata, f, indent=2)
            
    def stage_tmp_write(self, tmp_path: str, content: str):
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        with open(tmp_path, "w") as f:
            f.write(content)
            
    def atomic_rename_to_target(self, tmp_path: str, target_path: str):
        os.replace(tmp_path, target_path)
        
    def log_applied_change(self, target_path: str, metadata: dict):
        pass

class OrphanRecoveryScanner:
    def run(self):
        tmp_dir = ".dumbledoer/tmp"
        if not os.path.exists(tmp_dir):
            return
        import glob
        for file in glob.glob(os.path.join(tmp_dir, "*.tmp")):
            try:
                os.remove(file)
            except Exception:
                pass

class DumbleDoerCLI:
    def __init__(self):
        self.client = genai.Client()
        self.exit_stack = AsyncExitStack()
        self.mcp_sessions = {}
        self.local_tools = [read_file, write_file_with_review, execute_bash, update_memory_registry, run_rtk]
        self.gemini_tools = self.local_tools

    async def connect_mcp(self):
        # Connect to codegraph
        codegraph_params = StdioServerParameters(
            command="npx",
            args=["-y", "@colbymchenry/codegraph", "serve", "--mcp"]
        )
        codegraph_transport, codegraph_stream = await self.exit_stack.enter_async_context(stdio_client(codegraph_params))
        codegraph_session = await self.exit_stack.enter_async_context(ClientSession(codegraph_transport, codegraph_stream))
        await codegraph_session.initialize()
        self.mcp_sessions["codegraph"] = codegraph_session

        # Connect to context7
        context7_params = StdioServerParameters(
            command="npx",
            args=["-y", "context7", "serve", "--mcp"]
        )
        context7_transport, context7_stream = await self.exit_stack.enter_async_context(stdio_client(context7_params))
        context7_session = await self.exit_stack.enter_async_context(ClientSession(context7_transport, context7_stream))
        await context7_session.initialize()
        self.mcp_sessions["context7"] = context7_session

    async def run(self, command: str, args: list):
        await self.connect_mcp()
        try:
            print(f"DumbleDoer running command: {command}")
            self.chat_session = await self.client.aio.chats.create(model="gemini-2.5-flash", config={"tools": self.gemini_tools})
            response = await self.chat_session.send_message(f"Execute {command} with {args}")
            print(response.text)
        finally:
            await self.exit_stack.aclose()


async def main_async():
    parser = argparse.ArgumentParser(description="DumbleDoer CLI")
    parser.add_argument(
        "command",
        choices=["start", "execute", "resume", "report", "rollback", "update-docs"],
        help="The dumbledoer command to run"
    )
    args, unknown = parser.parse_known_args()
    
    cli = DumbleDoerCLI()
    await cli.run(args.command, unknown)

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
