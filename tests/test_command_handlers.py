import asyncio
import os
import shutil
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from yani_engine.commands.docs_handler import handle_update_docs
from yani_engine.commands.handlers import handle_rollback, handle_status
from yani_engine.commands.resume_handler import handle_resume
from yani_engine.core.state import TaskRegistryState, ASTMemoryMapper, _invalidate_task_cache


@pytest.fixture(autouse=True)
def reset_cache():
    _invalidate_task_cache()
    yield
    _invalidate_task_cache()


@pytest.mark.asyncio
async def test_docs_handler_symbol_change_detection(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        os.makedirs("docs", exist_ok=True)
        with open("docs/architecture.md", "w", encoding="utf-8") as f:
            f.write("# Architecture\nSee [[UserService]] for user management.\n<!-- ast-symbol: AuthService -->")

        with open("memory.md", "w", encoding="utf-8") as f:
            f.write("""# Memory

## Config
- docs_path: docs
- last_docs_update: 2026-08-01T00:00:00Z

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|

## Task Details
""")

        mock_orch = MagicMock()

        # Mock subprocess.run for git log and codegraph search
        def mock_subprocess_run(cmd, *args, **kwargs):
            if "git" in cmd:
                return SimpleNamespace(stdout="src/user.py\nsrc/auth.py", returncode=0)
            elif "codegraph" in cmd:
                # symbol search
                sym = cmd[-1]
                if sym == "UserService":
                    return SimpleNamespace(stdout="Symbol found in src/user.py", returncode=0)
                else:
                    return SimpleNamespace(stdout="No results found", returncode=0)
            return SimpleNamespace(stdout="", returncode=0)

        with patch("yani_engine.commands.docs_handler.subprocess.run", side_effect=mock_subprocess_run), \
             patch("rich.prompt.Prompt.ask", return_value="Y"):
            await handle_update_docs(mock_orch, ["--docs=docs"])

        tasks = await TaskRegistryState().load_tasks()
        assert len(tasks) == 1
        t_id = list(tasks.keys())[0]
        assert "Update docs: architecture.md" in tasks[t_id]["title"]
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_handlers_rollback_all_and_single_task(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # Create target file and rollback backup
        os.makedirs("src", exist_ok=True)
        with open("src/app.py", "w", encoding="utf-8") as f:
            f.write("MODIFIED CODE")

        # Prepare rollback snapshot
        os.makedirs(".yani/rollbacks/T-001/src", exist_ok=True)
        with open(".yani/rollbacks/T-001/src/app.py", "w", encoding="utf-8") as f:
            f.write("ORIGINAL UNTOUCHED CODE")

        with open("memory.md", "w", encoding="utf-8") as f:
            f.write("""# Memory

## Change Log
| Timestamp | Task ID | Target Path | Summary | Status | Rationale |
|---|---|---|---|---|---|
| 2026-08-29T00:00:00Z | T-001 | src/app.py | update app | applied | refactor |

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Feature A | change | completed | worker-1 | none | S-001 | chk_1 |

## Task Details
### T-001: Feature A
- **Status**: completed
- **Owner**: worker-1
- **Checkpoint**: chk_1
- **Notes**: Completed
""")

        mock_orch = MagicMock()

        # Rollback single task
        await handle_rollback(mock_orch, ["T-001"])

        with open("src/app.py", "r", encoding="utf-8") as f:
            restored = f.read()
        assert restored == "ORIGINAL UNTOUCHED CODE"

        tasks = await TaskRegistryState().load_tasks()
        assert tasks["T-001"]["status"] == "pending"
        assert tasks["T-001"]["owner"] == "—"
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_resume_handler_branching(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write("""# Memory

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Task 1 | change | in_progress | worker-1 | none | S-999 | none |
| T-002 | Task 2 | change | interrupted | worker-2 | none | S-999 | none |

## Task Details
### T-001: Task 1
- **Status**: in_progress
- **Owner**: worker-1

### T-002: Task 2
- **Status**: interrupted
- **Owner**: worker-2
""")

        mock_orch = MagicMock()

        # 1. Test Skip ('S')
        with patch("rich.prompt.Prompt.ask", return_value="S"), \
             patch("yani_engine.core.config.config.verbose", True):
            res = await handle_resume(mock_orch, [])
            assert res is None

        tasks = await TaskRegistryState().load_tasks()
        assert tasks["T-001"]["status"] == "deferred"
        assert tasks["T-002"]["status"] == "deferred"

        # 2. Reset and test Resume ('R')
        from yani_engine.core.state import _invalidate_task_cache

        _invalidate_task_cache()
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write("""# Memory

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Task 1 | change | in_progress | worker-1 | none | S-999 | none |

## Task Details
### T-001: Task 1
- **Status**: in_progress
""")
        _invalidate_task_cache()

        with patch("rich.prompt.Prompt.ask", return_value="R"), \
             patch("yani_engine.core.config.config.verbose", True):
            res = await handle_resume(mock_orch, [])
            assert res == "execute"

        tasks = await TaskRegistryState().load_tasks()
        assert tasks["T-001"]["status"] == "pending"
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_orchestrator_routing_no_legacy_crashes():
    from yani_engine.core.orchestrator import LLMOrchestrator

    with patch("yani_engine.commands.llm_handlers.handle_start", new_callable=AsyncMock) as mock_start, \
         patch("yani_engine.commands.llm_handlers.handle_iterate", new_callable=AsyncMock) as mock_iterate, \
         patch("yani_engine.core.mcp_manager.connect_mcp", new_callable=AsyncMock), \
         patch("yani_engine.core.telemetry.init_telemetry"):

        mock_orch = LLMOrchestrator()

        # Verify 'start' routes correctly without raising FileNotFoundError
        await mock_orch.run("start", [])
        mock_start.assert_called_once()

        # Verify 'iterate' routes correctly without raising ModuleNotFoundError
        await mock_orch.run("iterate", ["--prompt", "test"])
        mock_iterate.assert_called_once()

