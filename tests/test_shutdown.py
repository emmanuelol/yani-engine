import os
import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from yani_engine.core.orchestrator import LLMOrchestrator


@pytest.mark.asyncio
async def test_graceful_shutdown_concurrency(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write("## Task Registry\n| Task ID | Title | Type | Status | Depends On |\n|---|---|---|---|---|\n| T-001 | Test 1 | change | in_progress | none |\n| T-002 | Test 2 | change | in_progress | none |\n## Session Handoff Summary\n")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}), \
             patch("yani_engine.core.sandbox._teardown_warm_sandbox", new_callable=AsyncMock):
            orch = LLMOrchestrator(budget_limit=1000, plugin_dir=".")

            async def fake_task(tid):
                await orch._graceful_shutdown(task_id=tid)

            await asyncio.gather(fake_task("T-001"), fake_task("T-002"))

        with open("memory.md", "r", encoding="utf-8") as f:
            content = f.read()
        assert "Session Handoff Summary" in content
    finally:
        os.chdir(original_cwd)

