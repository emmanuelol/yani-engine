import asyncio
from yani_engine.core.orchestrator import LLMOrchestrator
from yani_engine.core.locks import _MEMORY_MUTEX
import os

async def run_stress_test():
    # Setup dummy memory.md
    with open("memory.md", "w") as f:
        f.write("## Task Registry\n| T-001 | Test 1 | change | pending | - | none | - | none |\n| T-002 | Test 2 | change | pending | - | none | - | none |\n| T-003 | Test 3 | change | pending | - | none | - | none |\n## Session Handoff Summary\n")
    
    orch = LLMOrchestrator(budget_limit=1000, plugin_dir=".")
    
    # Simulate a crash loop where tasks exhaust budget
    async def fake_task(tid):
        try:
            await orch._graceful_shutdown(task_id=tid)
        except Exception as e:
            print(f"Exception from {tid}: {e}")

    await asyncio.gather(fake_task("T-001"), fake_task("T-002"), fake_task("T-003"))
    
    print("Stress test completed.")
    with open("memory.md", "r") as f:
        print("Memory.md excerpt:")
        print(f.read())

asyncio.run(run_stress_test())
