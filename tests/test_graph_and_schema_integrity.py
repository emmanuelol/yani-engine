import os
import pytest

from yani_engine.core.state import register_task_batch, TaskRegistryState
from yani_engine.core.planner import WavePlanner
from yani_engine.core.orchestrator import DependencyGraphError


@pytest.mark.asyncio
async def test_duplicate_task_id_batch_rejection(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        content = """# Memory

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Base Task | change | pending | — | none | — | none |

## Task Details
### T-001: Base Task
- **Status**: pending
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        # 1. Attempt to register batch with ID that already exists
        batch_existing = [{"id": "T-001", "title": "Duplicate ID Task", "deps": "none"}]
        res = await register_task_batch(batch_existing)
        assert "Duplicate task ID T-001 already exists" in res

        # 2. Attempt to register batch with duplicate IDs within the same batch
        batch_internal_dup = [
            {"id": "T-002", "title": "First T-002", "deps": "none"},
            {"id": "T-002", "title": "Second T-002", "deps": "none"},
        ]
        res2 = await register_task_batch(batch_internal_dup)
        assert "Duplicate task ID T-002 in incoming batch" in res2

        # 3. Attempt to register batch with non-existent dependency
        batch_missing_dep = [
            {"id": "T-003", "title": "Task with missing dep", "deps": "T-999"}
        ]
        res3 = await register_task_batch(batch_missing_dep)
        assert "Dependency T-999 does not exist" in res3
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_cyclic_dependency_deadlock_detection(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # Create a direct cycle: T-001 depends on T-002, T-002 depends on T-001
        content = """# Memory

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Cyclic Task 1 | change | pending | — | T-002 | — | none |
| T-002 | Cyclic Task 2 | change | pending | — | T-001 | — | none |

## Task Details
### T-001: Cyclic Task 1
- **Status**: pending
- **Depends On**: T-002

### T-002: Cyclic Task 2
- **Status**: pending
- **Depends On**: T-001
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        planner = WavePlanner()
        with pytest.raises(DependencyGraphError, match="Dependency cycle or unresolvable dependencies detected"):
            await planner.get_pending_waves()
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_pydantic_tool_bouncers_rejection(tmp_path):
    """Verify that Pydantic validation bouncers catch malformed arguments before mutating state."""
    from yani_engine.core.state import update_task_registry_row

    # 1. Invalid Task ID pattern in update_task_registry_row
    res_id = await update_task_registry_row("Task-1", "completed")
    assert "State mutation rejected: Invalid arguments" in res_id
    assert "string_pattern_mismatch" in res_id or "pattern" in res_id

    # 2. Invalid Status enum in update_task_registry_row
    res_status = await update_task_registry_row("T-001", "finished")
    assert "State mutation rejected: Invalid arguments" in res_status
    assert "literal_error" in res_status or "input_value" in res_status

    # 3. Non-list payload in register_task_batch
    res_batch_type = await register_task_batch("invalid_payload_string")
    assert "State mutation rejected: Invalid arguments" in res_batch_type

    # 4. Missing required title or empty batch in register_task_batch
    res_batch_empty = await register_task_batch([])
    assert "State mutation rejected: Invalid arguments" in res_batch_empty

    res_batch_missing_title = await register_task_batch([{"deps": "none"}])
    assert "State mutation rejected: Invalid arguments" in res_batch_missing_title
    assert "missing" in res_batch_missing_title

