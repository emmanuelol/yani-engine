import sys
import asyncio
from yani_engine.core.orchestrator import LLMOrchestrator as YaniEngineCLI

async def test():
    cli = YaniEngineCLI()
    await cli.connect_mcp()
    tools = cli.gemini_tools
    for t in tools:
        print(f"Tool name: {getattr(t, '__name__', 'NO NAME')}")

if __name__ == "__main__":
    asyncio.run(test())
