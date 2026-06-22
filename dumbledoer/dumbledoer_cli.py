import os
import sys
from filelock import FileLock
import asyncio
import subprocess
from typing import List, Optional, Dict
from dotenv import load_dotenv
from google import genai
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from contextlib import AsyncExitStack

load_dotenv()
console = Console()
REGISTRY_LOCK = FileLock("memory.md.lock", timeout=10)

def read_file(path: str) -> str:
    """Reads a file from the file system."""
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {path}: {e}"

def write_file(path: str, content: str) -> str:
    """Writes content to a file on the file system."""
    try:
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing to file {path}: {e}"

def update_memory_registry(content: str) -> str:
    """Updates the memory.md file with the provided content.
    CRITICAL CONSTRAINT: You MUST preserve the entire Config block exactly as it was, including 'budget_limit' and 'budget_threshold_pct'. Do not compress, omit, or truncate the Config section under any circumstances.
    """
    with REGISTRY_LOCK:
        return write_file("memory.md", content)

def run_rtk(command: str) -> str:
    """
    Executes a heavy system command using the Rust Token Killer (rtk).
    Use this for all system management and heavy optimization tasks.
    """
    try:
        result = subprocess.run(["rtk", command], capture_output=True, text=True, check=True)
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
        
        self.local_tools = [read_file, write_file, update_memory_registry, run_rtk]
        self.gemini_tools = list(self.local_tools)

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

    async def start_chat(self, action: str, docs_path: Optional[str] = None):
        await self._init_mcp("context7", "npx", ["-y", "@upstash/context7-mcp"])
        await self._init_mcp("codegraph", "npx", ["-y", "--package=@colbymchenry/codegraph", "codegraph", "serve", "--mcp"])
        
        self.chat_session = self.client.aio.chats.create(
            model=self.model_id,
            config={"system_instruction": self._get_system_instructions(), "tools": self.gemini_tools}
        )
        
        console.print(Panel(f"DumbleDoer Executing: [bold blue]/{action}[/bold blue]", title="DumbleDoer"))
        response = await self.chat_session.send_message(f"Execute the /{action} command. Docs path: {docs_path}")
        if response.text:
            console.print(Markdown(response.text))

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "execute", "resume", "report", "rollback", "update-docs"])
    parser.add_argument("--docs", type=str)
    args = parser.parse_args()
    
    try:
        dumbledoer = DumbleDoerCLI()
        asyncio.run(dumbledoer.start_chat(args.command, args.docs))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
