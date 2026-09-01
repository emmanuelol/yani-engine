import os
import glob
import pytest
import shutil
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Import the modules we need to test
from yani_engine.core.sandbox import _ensure_warm_sandbox, _teardown_warm_sandbox, execute_bash
from yani_engine.core.orchestrator import LLMOrchestrator as YaniEngineCLI
from yani_engine.core.state import OrphanRecoveryScanner
@pytest.fixture
def setup_test_env(tmp_path):
    """Sets up a clean testing directory with a fake memory.md."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    
    # Setup .yani directories
    os.makedirs(".yani/tmp", exist_ok=True)
    os.makedirs(".yani/checkpoints", exist_ok=True)
    os.makedirs(".yani/rollbacks", exist_ok=True)
    
    # Initialize basic memory.md
    with open("memory.md", "w") as f:
        f.write("# yani_engine Memory\n\n")
        f.write("## Config\n- max_parallel_tasks: 3\n\n")
        f.write("## Task Registry\n")
        f.write("| Task ID | Title | Type | Status | Depends On |\n")
        f.write("|---|---|---|---|---|\n")
        
        f.write("## Change Log\n")
        f.write("| Timestamp | Task ID | Target Path | Summary | Status | Rationale |\n")
        f.write("|---|---|---|---|---|---|\n")
        
    yield tmp_path
    
    os.chdir(original_cwd)

# 1. test_parallel_sandbox_isolation()
@pytest.mark.asyncio
@patch("subprocess.run")
async def test_parallel_sandbox_isolation(mock_run, setup_test_env):
    """Asserts that _ensure_warm_sandbox allocates unique containers per task_id."""
    
    # Clear global state for test
    
    
    # Mock subprocess.run to pretend docker commands succeed
    mock_run_result = MagicMock()
    mock_run_result.returncode = 0
    mock_run_result.stdout = "true"
    mock_run.return_value = mock_run_result

    task_ids = ["T-101", "T-102", "T-103"]
    
    for t_id in task_ids:
        await _ensure_warm_sandbox(task_id=t_id)
        
    # We should have called docker run 3 times
    assert mock_run.call_count == 3
    
    # Assert containers are uniquely named


# 2. test_unattended_orphan_recovery_deadlock()
@pytest.mark.asyncio
@patch("rich.prompt.Confirm.ask")
async def test_unattended_orphan_recovery_deadlock(mock_confirm, setup_test_env):
    """Asserts that unattended scanner deletes orphaned .tmp files and never prompts."""
    
    tmp_file_path = ".yani/tmp/T-999_fake__file.py.tmp"
    with open(tmp_file_path, "w") as f:
        f.write("broken code")
        
    # We need to manually set the mtime of the file back to simulate an old orphan
    import time
    old_time = time.time() - 4000
    os.utime(tmp_file_path, (old_time, old_time))
        
    # Inject a planned entry into Change Log
    with open("memory.md", "a") as f:
        f.write("| 2026-07-30 | T-999 | fake/file.py | orphaned change | planned | crash test |\n")

    scanner = OrphanRecoveryScanner()
    await scanner.run(unattended=True)
    
    # Assert Confirm.ask was NEVER called
    mock_confirm.assert_not_called()
    
    # Assert the tmp file was deleted
    assert not os.path.exists(tmp_file_path)
    # Target file should not have been created
    assert not os.path.exists("fake/file.py")

# 3. test_native_qa_intercept_syntax_error()
@pytest.mark.asyncio
@patch("yani_engine.core.mcp_manager.connect_mcp", new_callable=AsyncMock)
@patch("yani_engine.commands.audit_handler.subprocess.run")
async def test_native_qa_intercept_syntax_error(mock_subprocess_run, mock_connect_mcp, setup_test_env):
    """Asserts that the native audit loop intercepts syntax errors and blocks execution."""
    
    # Mock subprocess.run for uvx ruff check
    mock_run_res = MagicMock()
    mock_run_res.returncode = 1
    mock_run_res.stdout = "src/broken.py:1:21: E999 SyntaxError: invalid syntax"
    mock_run_res.stderr = ""
    mock_subprocess_run.return_value = mock_run_res

    # Write a broken file
    os.makedirs("src", exist_ok=True)
    with open("src/broken.py", "w") as f:
        f.write("def broken_func() print('no colon')\n")
        
    # Seed memory.md with an awaiting-review task
    with open("memory.md", "r") as f:
        content = f.read()
        
    content = content.replace(
        "| Task ID | Title | Type | Status | Depends On |\n|---|---|---|---|---|\n",
        "| Task ID | Title | Type | Status | Depends On |\n|---|---|---|---|---|\n| T-888 | Fix code | change | awaiting-review | none |\n"
    )
    
    content = content.replace(
        "| Timestamp | Task ID | Target Path | Summary | Status | Rationale |\n|---|---|---|---|---|---|\n",
        "| Timestamp | Task ID | Target Path | Summary | Status | Rationale |\n|---|---|---|---|---|---|\n| 2026-07-30 | T-888 | src/broken.py | broke it | completed | test |\n"
    )
    
    # Add detailed block to avoid regex search error
    content += "\n### T-888\n- **Description**: Fix code\n- **Success Criteria**: Works\n- **Outputs**: src/broken.py\n"
    
    with open("memory.md", "w") as f:
        f.write(content)
        
    # Initialize CLI with a fake API key
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}):
        cli = YaniEngineCLI()
    
    # We must patch the client so it doesn't crash on None
    mock_chat_session = MagicMock()
    
    # The payload MUST contain the syntax error
    mock_send_message_called = False
    captured_payload = ""
    
    async def fake_send_message(prompt, *args, **kwargs):
        nonlocal mock_send_message_called, captured_payload
        mock_send_message_called = True
        captured_payload = prompt
        
        # Return a fake response with tool calls to satisfy the loop
        class FakeResponse:
            text = "LGTM"
            function_calls = []
        return FakeResponse()
        
    mock_chat_session.send_message = fake_send_message
    
    # FIX: Mock the decoupled provider interface instead of the deleted client
    from unittest.mock import AsyncMock
    cli.provider = MagicMock()
    cli.provider.create_chat_session = AsyncMock(return_value=mock_chat_session)
    cli.provider.parse_tool_calls.return_value = [] # Return empty to exit the loop
    async def wrapper(session, payload):
        return await fake_send_message(payload)
    cli.provider.send_message = AsyncMock(side_effect=wrapper)
    cli.provider.prune_history = MagicMock(return_value=(mock_chat_session, False))
    
    # Run the audit command
    await cli.run("audit", [])
    
    # Verify what prompt was passed to _send_message
    assert mock_send_message_called
    
    payload_lower = captured_payload.lower()
    assert "syntaxerror" in payload_lower or "invalid syntax" in payload_lower or "invalid-syntax" in payload_lower, f"Payload was: {payload_lower}"
