import asyncio
import sys
import pytest
from pydantic import BaseModel, Field, ValidationError

from yani_engine.core.state import execute_impact_analysis_safe, _format_validation_error


@pytest.mark.asyncio
async def test_execute_impact_analysis_safe_success():
    """Verify clean asynchronous execution and output capture."""
    cmd = [sys.executable, "-c", "print('— 5 affected symbol')"]
    out = await execute_impact_analysis_safe(cmd, timeout=5.0)
    assert "— 5 affected symbol" in out


@pytest.mark.asyncio
async def test_execute_impact_analysis_safe_timeout_kills_process_group():
    """Verify that hanging process groups are forcefully killed on timeout."""
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    with pytest.raises(TimeoutError, match="AST indexing exceeded"):
        await execute_impact_analysis_safe(cmd, timeout=0.3)


@pytest.mark.asyncio
async def test_execute_impact_analysis_safe_nonzero_exit():
    """Verify non-zero returncode raises RuntimeError with stderr capture."""
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('synthetic failure'); sys.exit(2)"]
    with pytest.raises(RuntimeError, match="CodeGraph execution failed: synthetic failure"):
        await execute_impact_analysis_safe(cmd, timeout=5.0)


def test_smart_truncation_preserves_head_and_tail():
    """Verify smart truncation retains head, tail, and truncation marker."""
    class DummyModel(BaseModel):
        field: str = Field(..., max_length=10)

    try:
        # Create a huge string with distinct head and tail
        DummyModel(field="HEAD_MARKER_" + ("Z" * 5000) + "_TAIL_MARKER")
    except ValidationError as e:
        msg = _format_validation_error(e, max_len=1400)
        assert "HEAD_MARKER_" in msg
        assert "_TAIL_MARKER" in msg
        assert "[TRUNCATED: Payload too large. Ensure descriptions are concise.]" in msg
        assert len(msg) <= 1600


def test_centralized_types_reexports():
    """Verify that domain exceptions and models re-export cleanly from both types and legacy modules."""
    import yani_engine.core.types as core_types
    import yani_engine.core.orchestrator as orch
    import yani_engine.core.state as state

    assert core_types.BudgetExhaustedException is orch.BudgetExhaustedException
    assert core_types.DependencyGraphError is orch.DependencyGraphError
    assert core_types.UpdateTaskStatusPayload is state.UpdateTaskStatusPayload is orch.UpdateTaskStatusPayload
    assert core_types.TaskBatchItem is state.TaskBatchItem is orch.TaskBatchItem
    assert core_types.TaskBatchPayload is state.TaskBatchPayload is orch.TaskBatchPayload


def test_dynamic_timeout_calculation():
    """Verify dynamic timeout bounds and scaling behavior."""
    from unittest.mock import patch
    from yani_engine.core.state import get_dynamic_timeout

    with patch("yani_engine.core.state._get_tracked_file_count", return_value=0):
        assert get_dynamic_timeout() == 5.0

    with patch("yani_engine.core.state._get_tracked_file_count", return_value=500):
        assert get_dynamic_timeout() == 15.0

    with patch("yani_engine.core.state._get_tracked_file_count", return_value=5000):
        assert get_dynamic_timeout() == 60.0


@pytest.mark.asyncio
async def test_json_state_mirror_sync(tmp_path):
    """Verify atomic state mirroring to .yani/state.json."""
    import json
    import os
    from yani_engine.core.state import _sync_json_mirror

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        sample_state = {
            "T-001": {
                "title": "[Core] Hardened Task",
                "type": "change",
                "status": "in_progress",
                "owner": "test-session",
                "deps": "none",
                "checkpoint": "chk_12345"
            }
        }
        _sync_json_mirror(sample_state)

        json_path = os.path.join(".yani", "state.json")
        assert os.path.exists(json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data == sample_state
        assert data["T-001"]["status"] == "in_progress"
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_end_to_end_flush_generates_json_mirror(tmp_path):
    """Verify that update_task_registry_row + flush_task_registry generates .yani/state.json."""
    import json
    import os
    from yani_engine.core.state import update_task_registry_row, flush_task_registry, _invalidate_task_cache

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        _invalidate_task_cache()
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

        await update_task_registry_row("T-001", "in_progress", new_owner="worker-1")
        await flush_task_registry()

        json_path = os.path.join(".yani", "state.json")
        assert os.path.exists(json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            state_json = json.load(f)

        assert "T-001" in state_json
        assert state_json["T-001"]["status"] == "in_progress"
        assert state_json["T-001"]["owner"] == "worker-1"
    finally:
        _invalidate_task_cache()
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_flush_task_registry_graceful_degradation_on_json_error(tmp_path):
    """Verify that flush_task_registry does not crash if secondary JSON mirror fails."""
    from unittest.mock import patch
    import os
    from yani_engine.core.state import update_task_registry_row, flush_task_registry, _invalidate_task_cache

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        _invalidate_task_cache()
        content = """# Memory

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Base Task | change | pending | — | none | — | none |
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        await update_task_registry_row("T-001", "in_progress")
        # Injected catastrophic failure in secondary mirror
        with patch("yani_engine.core.state._sync_json_mirror", side_effect=RuntimeError("Simulated disk full")):
            # Must not raise RuntimeError
            await flush_task_registry()

        # Primary source of truth memory.md MUST still be cleanly updated
        with open("memory.md", "r", encoding="utf-8") as f:
            mem = f.read()
        assert "in_progress" in mem
    finally:
        _invalidate_task_cache()
        os.chdir(original_cwd)


def test_get_dynamic_timeout_observability(caplog):
    """Verify that get_dynamic_timeout emits debug telemetry log."""
    import logging
    from yani_engine.core.state import get_dynamic_timeout

    with caplog.at_level(logging.DEBUG):
        timeout = get_dynamic_timeout()
        assert timeout >= 5.0
        assert any("Calculated dynamic timeout:" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_table_insertion_ignores_stray_pipes(tmp_path):
    """Verify table row insertion ignores non-table lines with pipes."""
    import os
    from yani_engine.core.state import ASTMemoryMapper, format_markdown_row, register_task_batch, _invalidate_task_cache

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        _invalidate_task_cache()
        content = """# Memory

## Change Log
| Timestamp | Task ID | Target Path | Summary | Status | Rationale |
|---|---|---|---|---|---|
| 2026-08-29T00:00:00 | T-001 | main.py | init | applied | bootstrap |

> Note: this is a blockquote | with a stray pipe | that should not count as table row

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Task One | change | completed | — | none | — | none |

| Invalid non-task row |

## Task Details
### T-001: Task One
- **Status**: completed
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        # 1. Test append_to_markdown_table ignores blockquote with pipe
        new_log = format_markdown_row(["2026-08-29T01:00:00", "T-002", "app.py", "update", "applied", "feat"])
        success = ASTMemoryMapper.append_to_markdown_table("memory.md", "Change Log", new_log)
        assert success

        with open("memory.md", "r", encoding="utf-8") as f:
            mem1 = f.read()

        lines = mem1.splitlines()
        row_t1 = next(i for i, l in enumerate(lines) if "T-001 | main.py" in l)
        row_t2 = next(i for i, l in enumerate(lines) if "T-002 | app.py" in l)
        assert row_t2 == row_t1 + 1

        # 2. Test register_task_batch inserts after T-001, not after invalid row
        batch = [{"id": "T-002", "title": "[Core] Task Two", "deps": "none"}]
        res = await register_task_batch(batch)
        assert "Successfully registered tasks T-002" in res

        with open("memory.md", "r", encoding="utf-8") as f:
            mem2 = f.read()

        lines2 = mem2.splitlines()
        reg_t1 = next(i for i, l in enumerate(lines2) if "T-001 | Task One" in l)
        reg_t2 = next(i for i, l in enumerate(lines2) if "T-002 | [Core] Task Two" in l)
        assert reg_t2 == reg_t1 + 1
    finally:
        _invalidate_task_cache()
        os.chdir(original_cwd)



