import asyncio
import os
import typer
from rich.console import Console
from google import genai

console = Console()
app = typer.Typer(name="dumbledoer")

async def initialize_mcp_servers():
    """
    Initializes stdio_client connections to two MCP servers using npx:
    - @upstash/context7-mcp
    - @colbymchenry/codegraph
    """
    console.print("[bold green]Initializing MCP servers via stdio_client...[/bold green]")
    # Placeholder for MCP initialization logic:
    # mcp_context7 = await start_stdio_client("npx", ["-y", "@upstash/context7-mcp"])
    # mcp_codegraph = await start_stdio_client("npx", ["-y", "@colbymchenry/codegraph"])
    pass

# Tool bindings for Gemini
def read_file(filepath: str) -> str:
    """Read a file from the disk."""
    with open(filepath, "r") as f:
        return f.read()

def write_file(filepath: str, content: str) -> None:
    """Write content to a file on disk."""
    with open(filepath, "w") as f:
        f.write(content)

def update_project_state_registry(key: str, value: str) -> None:
    """Updates the project state registry in memory.md."""
    console.print(f"[bold cyan]Updating project state:[/bold cyan] {key} -> {value}")
    # Logic to parse and update memory.md goes here
    pass

async def main_loop():
    """Main Orchestrator Loop"""
    console.print("[bold blue]Starting DumbleDoer Orchestrator...[/bold blue]")
    
    # 1. Initialize MCP connections
    await initialize_mcp_servers()
    
    # 2. Initialize Gemini Client
    client = genai.Client()
    
    # 3. Bind local functions as Gemini tools
    tools = [read_file, write_file, update_project_state_registry]
    
    console.print("[bold green]Agent loop running. Waiting for commands...[/bold green]")
    # TODO: Implement command listener and workflow engine

@app.command()
def start():
    """Run the main DumbleDoer orchestrator."""
    asyncio.run(main_loop())

if __name__ == "__main__":
    app()
