import asyncio
import os
import subprocess
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from yani_engine.core.mcp_manager import PersistentCircuitBreaker, connect_mcp
from yani_engine.core.orchestrator import LLMOrchestrator


def test_persistent_circuit_breaker_lifecycle(tmp_path):
    cb = PersistentCircuitBreaker(
        name="test_service",
        threshold=2,
        recovery_window=10,
        state_dir=str(tmp_path),
    )

    # 1. Initially closed
    assert not cb.is_open()

    # 2. Record 1st failure -> still closed
    cb.record_failure()
    assert not cb.is_open()

    # 3. Record 2nd failure -> trips OPEN
    cb.record_failure()
    assert cb.is_open()

    # 4. Before recovery window -> stays OPEN
    assert cb.is_open()

    # 5. Simulate recovery window expiration -> Half-Open (returns False for trial)
    with patch("time.time", return_value=time.time() + 15):
        assert not cb.is_open()
        # Failing during trial trips back to OPEN immediately
        cb.record_failure()
        assert cb.is_open()

    # 6. Record success -> resets to closed
    cb.record_success()
    assert not cb.is_open()


@pytest.mark.asyncio
async def test_connect_mcp_subprocess_timeout(tmp_path):
    orchestrator = LLMOrchestrator()
    orchestrator.gemini_tools = []
    orchestrator.mcp_sessions = {}
    orchestrator.mcp_locks = {}

    with patch("os.path.exists", return_value=False), \
         patch("os.makedirs"), \
         patch("asyncio.to_thread", side_effect=subprocess.TimeoutExpired(cmd="npx", timeout=15.0)), \
         patch("yani_engine.core.mcp_manager.PersistentCircuitBreaker") as mock_cb_cls:

        mock_cb = MagicMock()
        mock_cb.is_open.return_value = False
        mock_cb_cls.return_value = mock_cb

        await connect_mcp(orchestrator)

        mock_cb.record_failure.assert_called()
        assert "codegraph" not in orchestrator.mcp_sessions
        assert not orchestrator.is_codegraph_active


@pytest.mark.asyncio
async def test_connect_mcp_rpc_timeout(tmp_path):
    orchestrator = LLMOrchestrator()
    orchestrator.gemini_tools = []
    orchestrator.mcp_sessions = {}
    orchestrator.mcp_locks = {}

    with patch("os.path.exists", return_value=True), \
         patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()), \
         patch("yani_engine.core.mcp_manager.PersistentCircuitBreaker") as mock_cb_cls:

        mock_cb = MagicMock()
        mock_cb.is_open.return_value = False
        mock_cb_cls.return_value = mock_cb

        await connect_mcp(orchestrator)

        mock_cb.record_failure.assert_called()
        assert "codegraph" not in orchestrator.mcp_sessions


@pytest.mark.asyncio
async def test_connect_mcp_circuit_breaker_open_skips(tmp_path):
    orchestrator = LLMOrchestrator()
    orchestrator.gemini_tools = []
    orchestrator.mcp_sessions = {}
    orchestrator.mcp_locks = {}

    with patch("asyncio.to_thread") as mock_to_thread, \
         patch("yani_engine.core.mcp_manager.PersistentCircuitBreaker") as mock_cb_cls:

        mock_cb = MagicMock()
        mock_cb.is_open.return_value = True
        mock_cb_cls.return_value = mock_cb

        await connect_mcp(orchestrator)

        # Subprocess should not be called at all when circuit breaker is OPEN
        mock_to_thread.assert_not_called()
        assert len(orchestrator.mcp_sessions) == 0


def test_persistent_circuit_breaker_atomic_write(tmp_path):
    cb = PersistentCircuitBreaker(
        name="atomic_test",
        threshold=2,
        recovery_window=10,
        state_dir=str(tmp_path),
    )
    cb.record_failure()
    assert cb.state_file.exists()
    import json
    data = json.loads(cb.state_file.read_text())
    assert data["failures"] == 1
    # Ensure temporary file was replaced and cleaned up
    tmp_files = list(tmp_path.glob("*.tmp*"))
    assert len(tmp_files) == 0


@pytest.mark.asyncio
async def test_connect_mcp_codegraph_empty_dir_triggers_init(tmp_path):
    orchestrator = LLMOrchestrator()
    orchestrator.gemini_tools = []
    orchestrator.mcp_sessions = {}
    orchestrator.mcp_locks = {}

    def exists_side_effect(path):
        if path == ".codegraph/codegraph.json":
            return False
        if path == ".codegraph":
            return True
        return False

    with patch("os.path.exists", side_effect=exists_side_effect), \
         patch("os.makedirs"), \
         patch("asyncio.to_thread") as mock_to_thread, \
         patch("yani_engine.core.mcp_manager.PersistentCircuitBreaker") as mock_cb_cls:

        mock_to_thread.side_effect = subprocess.TimeoutExpired(cmd="npx", timeout=15.0)
        mock_cb = MagicMock()
        mock_cb.is_open.return_value = False
        mock_cb_cls.return_value = mock_cb

        await connect_mcp(orchestrator)

        # Must have triggered npx codegraph init even though .codegraph exists
        mock_to_thread.assert_called_once()

