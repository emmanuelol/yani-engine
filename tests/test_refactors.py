import os
import asyncio
import time
from unittest.mock import patch, mock_open, MagicMock
from dumbledoer.dumbledoer_cli import write_file_with_review, execute_bash, run_rtk, DumbleDoerCLI
import pytest

def test_execute_bash_sandbox():
    with patch("dumbledoer.dumbledoer_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="mocked output", returncode=0)
        output = execute_bash("echo 'hello'")
        assert output == "mocked output"
        
        # Verify docker invocation
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd_list = args[0]
        assert "docker" in cmd_list
        assert "run" in cmd_list
        assert "ubuntu:latest" in cmd_list
        assert "bash" in cmd_list
        assert "-c" in cmd_list
        assert "echo 'hello'" in cmd_list
        assert kwargs.get("shell") is not True

def test_run_rtk_sandbox():
    with patch("dumbledoer.dumbledoer_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="mocked rtk output", returncode=0)
        output = run_rtk("gain --history")
        assert output == "RTK Output: mocked rtk output"
        
        # Verify docker invocation
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd_list = args[0]
        assert "docker" in cmd_list
        assert "run" in cmd_list
        assert "ubuntu:latest" in cmd_list
        assert "rtk" in cmd_list
        assert "gain" in cmd_list
        assert "--history" in cmd_list
        assert kwargs.get("shell") is not True

def test_write_file_with_review():
    with patch("dumbledoer.dumbledoer_cli.subprocess.run") as mock_run, \
         patch("dumbledoer.dumbledoer_cli.input", return_value="y"), \
         patch("builtins.open", mock_open(read_data="new mocked content")), \
         patch("os.makedirs"), \
         patch("os.replace") as mock_replace, \
         patch("os.path.exists", return_value=True):
         
        result = write_file_with_review("test/dummy/file.txt", "mock content")
        
        # Verify new-window is passed
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert "--new-window" in args[0]
        assert "--diff" in args[0]
        
        mock_replace.assert_called_once()
        assert "Final File Content:\nnew mocked content" in result

def test_async_event_loop_protection():
    async def _test():
        cli = DumbleDoerCLI(api_key="dummy")
        
        def slow_sync_func():
            time.sleep(0.1)
            return "done"
            
        async_func = cli._create_async_wrapper(slow_sync_func)
        
        start = time.time()
        
        async def background_task():
            await asyncio.sleep(0.05)
            return "bg_done"

        results = await asyncio.gather(
            async_func(),
            background_task()
        )
        duration = time.time() - start
        
        assert results[0] == "done"
        assert results[1] == "bg_done"
        # Thread runs concurrently with asyncio.sleep so duration should be just ~0.1s
        assert 0.1 <= duration < 0.2

    asyncio.run(_test())
