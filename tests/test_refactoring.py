import asyncio
import os
import pytest
from dumbledoer.core.state import TaskRegistryState, update_task_registry_row
from dumbledoer.core.orchestrator import LLMOrchestrator, BudgetExhaustedException
from dumbledoer.core.llm_provider import AbstractLLMProvider
from google.genai.types import Part

class MockLLMProvider(AbstractLLMProvider):
    def __init__(self):
        self.session_created = False
        self.messages_sent = []
        
    async def create_chat_session(self, model_name: str, tools: list) -> any:
        self.session_created = True
        return {"mock_session": True}
        
    async def send_message(self, session: any, payload: str | list) -> any:
        self.messages_sent.append(payload)
        class MockResponse:
            def __init__(self):
                self.text = "Executed mock tools"
                self.function_calls = []
        return MockResponse()
        
    def parse_tool_calls(self, response: any) -> list:
        return []
        
    def format_tool_response(self, tool_name: str, result: str) -> any:
        return Part.from_function_response(name=tool_name, response={"result": result})
        
    def format_tool_error(self, tool_name: str, error: str) -> any:
        return Part.from_function_response(name=tool_name, response={"error": error})

    def prune_history(self, session: any, max_turns: int) -> tuple[any, bool]:
        return session, False

@pytest.mark.asyncio
async def test_update_task_registry_concurrency():
    state = TaskRegistryState()
    
    # 1. Setup mock memory.md with tasks
    with open("memory.md", "w") as f:
        f.write("## Task Registry\n")
        f.write("| Task ID | Title | Type | Status | Owner | Deps | Session | Checkpoint |\n")
        f.write("|---------|-------|------|--------|-------|------|---------|------------|\n")
        for i in range(10):
            f.write(f"| T-{i:03d} | Test {i} | test | pending | — | none | session1 | none |\n")
            
    # 2. Spawn 10 concurrent async tasks
    async def update_task(task_id: str):
        await update_task_registry_row(task_id, "completed", f"worker-{task_id}")
        
    tasks = [update_task(f"T-{i:03d}") for i in range(10)]
    await asyncio.gather(*tasks)
    
    # 3. Read memory.md and assert all 10 state changes exist
    updated_tasks = state._load_tasks_unlocked()
    for i in range(10):
        t_id = f"T-{i:03d}"
        assert t_id in updated_tasks
        assert updated_tasks[t_id]["status"] == "completed"
        assert updated_tasks[t_id]["owner"] == f"worker-{t_id}"
        
@pytest.mark.asyncio
async def test_mock_llm_provider():
    provider = MockLLMProvider()
    orchestrator = LLMOrchestrator(provider=provider)
    
    # Run the orchestrator with mock provider
    await orchestrator.execute_task("T-001", "Mock Task")
    
    assert provider.session_created is True
    assert len(provider.messages_sent) > 0

@pytest.mark.asyncio
async def test_wave_planner():
    from dumbledoer.core.planner import WavePlanner
    
    with open("memory.md", "w") as f:
        f.write("## Task Registry\n")
        f.write("| Task ID | Title | Type | Status | Owner | Deps | Session | Checkpoint |\n")
        f.write("|---------|-------|------|--------|-------|------|---------|------------|\n")
        for i in range(1, 10):
            f.write(f"| T-{i:03d} | Test {i} | test | pending | — | none | session1 | none |\n")
            
    planner = WavePlanner(start_at_index=7)
    waves = await planner.get_pending_waves()
    
    # Extract all task IDs from waves
    all_task_ids = [t['id'] for wave in waves for t in wave]
    
    assert "T-001" not in all_task_ids
    assert "T-006" not in all_task_ids
    assert "T-007" in all_task_ids
    assert "T-009" in all_task_ids
