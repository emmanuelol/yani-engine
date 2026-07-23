import pytest
import os
import asyncio
from unittest.mock import patch, MagicMock

from dumbledoer.dumbledoer_cli import DumbleDoerCLI, CheckpointManager, execute_bash

@pytest.mark.asyncio
async def test_dumbledoer_cli_run():
    cli = DumbleDoerCLI()
    
    with patch.object(cli, 'connect_mcp', new_callable=MagicMock) as mock_connect:
        mock_connect.return_value = asyncio.Future()
        mock_connect.return_value.set_result(None)
        
        with patch.object(cli.exit_stack, 'aclose', new_callable=MagicMock) as mock_aclose:
            mock_aclose.return_value = asyncio.Future()
            mock_aclose.return_value.set_result(None)
            
            await cli.run("start", ["--dry-run"])
            
            mock_connect.assert_called_once()
            mock_aclose.assert_called_once()

@pytest.mark.asyncio
async def test_execute_bash_docker():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "Docker execution success"
        mock_run.return_value = mock_result
        
        result = await execute_bash("echo 'test'")
        
        mock_run.assert_called_once_with(
            ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{os.getcwd()}:/workspace", "-w", "/workspace", "dumbledoer-base:latest", "bash", "-c", "echo 'test'"],
            capture_output=True,
            text=True,
            check=True
        )
        assert result == "Docker execution success"

@pytest.mark.asyncio
async def test_checkpoint_manager_atomic_rename():
    manager = CheckpointManager()
    
    with patch("os.replace") as mock_replace:
        await manager.atomic_rename_to_target("file.tmp", "file.txt")
        mock_replace.assert_called_once_with("file.tmp", "file.txt")

@pytest.mark.asyncio
async def test_checkpoint_manager_write_rollback_copy():
    manager = CheckpointManager()
    
    with patch("os.path.exists") as mock_exists, \
         patch("os.makedirs") as mock_makedirs, \
         patch("shutil.copy2") as mock_copy:
        
        # Scenario 1: rollback_path exists, should return immediately
        mock_exists.side_effect = lambda path: path == "rollback.bak"
        await manager.write_rollback_copy("target.txt", "rollback.bak")
        mock_copy.assert_not_called()
        
        # Scenario 2: rollback_path does not exist, target_path exists
        mock_copy.reset_mock()
        mock_exists.side_effect = lambda path: path == "target.txt"
        await manager.write_rollback_copy("target.txt", "rollback.bak")
        mock_makedirs.assert_called_once_with("", exist_ok=True)
        mock_copy.assert_called_once_with("target.txt", "rollback.bak")
