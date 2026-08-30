import pytest
import os
import re

def test_token_bleed():
    """Verify that agent loops are strictly clamped to avoid token bleeds.

    The effort→iteration mapping was extracted from orchestrator.py into
    task_executor.py (Phase 5 refactor). The guard is satisfied if the
    clamp exists anywhere in the task execution path.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    # The per-command default cap lives in agent_loop.py
    agent_loop_src = os.path.join(repo_root, "yani_engine/core/agent_loop.py")
    with open(agent_loop_src, "r") as f:
        loop_content = f.read()

    # The per-task effort→iteration map was moved to task_executor.py
    task_exec_src = os.path.join(repo_root, "yani_engine/core/task_executor.py")
    with open(task_exec_src, "r") as f:
        exec_content = f.read()

    assert "max_iterations=15" in loop_content, "Per-command agent loop iteration clamping is missing from agent_loop!"
    assert '"medium": 25' in exec_content, "Fallback effort→iteration limits are missing from task_executor!"


@pytest.mark.asyncio
async def test_pydantic_validation_error_truncation():
    """Verify that massive invalid payloads are strictly truncated to prevent token window explosion."""
    from yani_engine.core.state import register_task_batch, update_task_registry_row

    # 1. Massive invalid field in register_task_batch payload (e.g. 50,000 characters)
    huge_invalid_tasks = [
        {
            "id": "INVALID_" + ("X" * 50000),
            "title": "[Core] Valid Title",
            "task_type": "change",
        }
    ]
    res_batch = await register_task_batch(huge_invalid_tasks)
    assert "State mutation rejected: Invalid arguments" in res_batch
    assert "[TRUNCATED: Payload too large" in res_batch
    assert len(res_batch) <= 1600

    # 2. Massive invalid status in update_task_registry_row
    res_status = await update_task_registry_row("T-001", "INVALID_" + ("X" * 10000))
    assert "State mutation rejected: Invalid arguments" in res_status
    assert "[TRUNCATED: Payload too large" in res_status
    assert len(res_status) <= 1600


