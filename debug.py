import asyncio
from yani_engine.core.orchestrator import LLMOrchestrator
async def main():
    orch = LLMOrchestrator(budget_limit=1000)
    try:
        await orch.execute_task("T-001", description="Test task")
    except Exception as e:
        print(f"Exception: {e}")
asyncio.run(main())
