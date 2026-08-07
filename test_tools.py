import sys
import asyncio
from dumbledoer.core.orchestrator import LLMOrchestrator as DumbleDoerCLI

async def test():
    cli = DumbleDoerCLI()
    await cli.connect_mcp()
    tools = cli.gemini_tools
    for t in tools:
        print(f"Tool name: {getattr(t, '__name__', 'NO NAME')}")

asyncio.run(test())
