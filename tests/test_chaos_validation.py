import asyncio
import os
import pytest
import shutil
import json
from unittest.mock import patch, MagicMock, AsyncMock

from dumbledoer.dumbledoer_cli import (
    write_file_with_review, 
    TaskRegistryState, 
    execute_bash, 
    update_memory_registry,
    DumbleDoerCLI,
    BudgetExhaustedException,
    run_rtk
)

@pytest.fixture(autouse=True)
def mock_env():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        yield

@pytest.mark.asyncio
async def test_suite_1_swarm_batch_gate(tmp_path):
    """Test Suite 1: Swarm Batch-Gate & Isolation Validation"""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with open("memory.md", "w") as f:
            f.write("## Change Log\n| Timestamp | Task ID | Target Path | Action | Status | Rationale |\n| --- | --- | --- | --- | --- | --- |\n\n## Checkpoint Registry\n| Checkpoint ID | Task ID | Step | Session ID | Files Snapshotted |\n| --- | --- | --- | --- | --- |\n")
        # Create dummy target files and tasks
        for i in range(5):
            with open(f"file_{i}.txt", "w") as f:
                f.write(f"old content {i}")
                
        # Mock TaskRegistryState to load dummy tasks
        state = TaskRegistryState()
        dummy_tasks = {
            f"T-00{i}": {"id": f"T-00{i}", "status": "in-progress", "deps": [], "title": "test", "desc": "test"}
            for i in range(5)
        }
        state.save_tasks(dummy_tasks)
        
        cli = DumbleDoerCLI()
        
        # Run 5 tasks in parallel
        with patch("dumbledoer.dumbledoer_cli.subprocess.run") as mock_run:
            results = await asyncio.gather(*[
                write_file_with_review(f"file_{i}.txt", f"new content {i}")
                for i in range(5)
            ])
            # Assert no blocking subprocess run called during staging
            mock_run.assert_not_called()
            
        import glob
        tmp_files = glob.glob(".dumbledoer/tmp/*.tmp")
        assert len(tmp_files) == 5
        
        # We mock the Prompt.ask to simulate "S", then "file_1.txt"
        with patch("rich.prompt.Prompt.ask", side_effect=["S", "file_1.txt"]), \
             patch("dumbledoer.dumbledoer_cli.subprocess.run") as mock_code:
            await cli.batch_diff_review(tmp_files)
            
            # Assert exactly one batched VS Code diff window is presented
            mock_code.assert_called_once()
            args = mock_code.call_args[0][0]
            assert args[0] == "code"
            assert args[1] == "--wait"
            assert len(args) == 2 + 5  # 5 tmp files
            
        # Assert 4 approved files atomically renamed, 1 rejected file rolled back (or tmp discarded)
        assert os.path.exists("file_0.txt")
        assert os.path.exists("file_2.txt")
        assert os.path.exists("file_3.txt")
        assert os.path.exists("file_4.txt")
        
        with open("file_0.txt", "r") as f: assert f.read() == "new content 0"
        with open("file_1.txt", "r") as f: assert f.read() == "old content 1"  # Rejected, should be old content
        
    finally:
        os.chdir(original_cwd)

@pytest.mark.asyncio
async def test_suite_2_state_integrity(tmp_path):
    """Test Suite 2: State Integrity Stress Test"""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with open("memory.md", "w") as f:
            f.write("- sandbox_mode: native\n\nTARGET_BLOCK\n")
            
        async def writer(i):
            return await update_memory_registry("TARGET_BLOCK", f"TARGET_BLOCK\n{i}")
            
        async def reader():
            res = await execute_bash("echo test")
            return res
                
        with patch("dumbledoer.dumbledoer_cli.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok", returncode=0)
            writers = [writer(i) for i in range(150)]
            readers = [reader() for i in range(50)]
            
            await asyncio.gather(*writers, *readers)
            
            assert mock_run.call_count == 50
            for call in mock_run.call_args_list:
                args = call[0][0]
                assert "target-repo-img" in args, f"Corrupted read: args were {args}"
    finally:
        os.chdir(original_cwd)

@pytest.mark.asyncio
async def test_suite_3_rtk_threshold(tmp_path):
    """Test Suite 3: RTK Threshold Trigger"""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with open("memory.md", "w") as f:
            f.write("## Config\n- sandbox_mode: native\n\n")
            
        cli = DumbleDoerCLI()
        cli.gemini_tools = []
        mock_chat = AsyncMock()
        
        mock_chat.send_message.side_effect = [
            BudgetExhaustedException("Budget Exhausted"), 
            MagicMock(text="success")
        ]
        cli.client = MagicMock()
        cli.client.aio.chats.create.return_value = mock_chat
        
        with patch("dumbledoer.dumbledoer_cli.run_rtk", new_callable=AsyncMock) as mock_rtk, \
             patch.object(cli, "_graceful_shutdown", new_callable=AsyncMock) as mock_shutdown:
             
            mock_rtk.return_value = "Saved 1000 tokens"
            
            await cli.execute_task("T-001", "test")
            
            mock_rtk.assert_called_once_with("gain")
            mock_shutdown.assert_not_called()
            
            mock_chat.send_message.side_effect = [
                BudgetExhaustedException("Budget Exhausted"),
                BudgetExhaustedException("Budget Exhausted")
            ]
            await cli.execute_task("T-002", "test")
            assert mock_rtk.call_count == 2
            mock_shutdown.assert_called_once_with("T-002")
    finally:
        os.chdir(original_cwd)

def test_suite_4_string_escape_resilience(tmp_path):
    """Test Suite 4: String Escape Resilience"""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        complex_desc = '''This is a test description.
        It has multiple lines.
        ```python
        # Here is a comment
        def foo():
            return {"json": "payload", "escaped": "\\n\\t"}
        ```
        And some more text here.
        '''
        
        state = TaskRegistryState()
        state.save_tasks({
            "T-999": {
                "id": "T-999",
                "desc": complex_desc,
                "title": "Complex task",
                "status": "pending",
                "deps": []
            }
        })
        
        cli = DumbleDoerCLI()
        waves = cli.get_pending_waves()
        
        assert len(waves) == 1
        assert len(waves[0]) == 1
        task = waves[0][0]
        
        assert task["id"] == "T-999"
        assert task["desc"] == complex_desc
    finally:
        os.chdir(original_cwd)

@pytest.mark.asyncio
async def test_suite_1b_headless_diff_validation(tmp_path):
    """Test Suite 1b: Headless Diff Validation"""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with open("memory.md", "w") as f:
            f.write("## Change Log\n| Timestamp | Task ID | Target Path | Action | Status | Rationale |\n| --- | --- | --- | --- | --- | --- |\n\n## Checkpoint Registry\n| Checkpoint ID | Task ID | Step | Session ID | Files Snapshotted |\n| --- | --- | --- | --- | --- |\n")
            
        with open("file_1.txt", "w") as f:
            f.write("old 1\n")
        with open("1234_file_1.txt.tmp", "w") as f:
            f.write("new 1\n")
            
        with open("file_2.txt", "w") as f:
            f.write("old 2\n")
        with open("5678_file_2.txt.tmp", "w") as f:
            f.write("new 2\n")
            
        tmp_files = [
            os.path.abspath("1234_file_1.txt.tmp"),
            os.path.abspath("5678_file_2.txt.tmp")
        ]
        
        cli = DumbleDoerCLI()
        
        with patch("dumbledoer.dumbledoer_cli.GUI_DIFF_ENABLED", False, create=True), \
             patch("rich.console.Console.print") as mock_print, \
             patch("dumbledoer.dumbledoer_cli.subprocess.run") as mock_run, \
             patch("rich.prompt.Prompt.ask", return_value="Y"):
             
            await cli.batch_diff_review(tmp_files)
            
            mock_run.assert_not_called()
            
            from rich.syntax import Syntax
            syntax_calls = [
                call.args[0] 
                for call in mock_print.call_args_list 
                if call.args and isinstance(call.args[0], Syntax)
            ]
            
            assert len(syntax_calls) == 2
            
            diffs = [syn.code for syn in syntax_calls]
            
            assert any("-old 1" in d and "+new 1" in d for d in diffs)
            assert any("-old 2" in d and "+new 2" in d for d in diffs)
            
    finally:
        os.chdir(original_cwd)
