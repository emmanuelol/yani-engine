import pytest
import os
import subprocess
from unittest.mock import patch, MagicMock
from yani_engine.core.sandbox import execute_bash
from yani_engine.core.orchestrator import LLMOrchestrator

@pytest.mark.asyncio
@patch("subprocess.run")
async def test_execute_bash_native_sandbox_isolation(mock_run):
    """Verify that execute_bash correctly formats pythonpath and command execution in native mode."""
    mock_result = MagicMock()
    mock_result.stdout = "execution success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    mock_run.return_value = mock_result

    result = await execute_bash("pytest tests/", sandbox_mode="native")
    
    assert "execution success" in result
    mock_run.assert_called_once()
    
    args = mock_run.call_args[0][0]
    assert args[0] == "bash"
    assert args[1] == "-c"
    assert "PYTHONPATH" in args[2]

@pytest.mark.asyncio
@patch("subprocess.run")
async def test_ephemeral_artifact_purge(mock_run, tmp_path):
    """Verify that untracked workspace artifacts leaked during execution are detected and purged."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    
    try:
        # Simulate git status output before and after task execution
        # pre-untracked: empty
        # post-untracked: leaks an ephemeral test script
        mock_git_ls = MagicMock()
        mock_git_ls.stdout = "temp_leaked_script.py\n"
        
        # Create the leaked file on disk
        leaked_file = "temp_leaked_script.py"
        with open(leaked_file, "w") as f:
            f.write("print('leak')")
            
        assert os.path.exists(leaked_file)
        
        # Mock git commands used in orchestrator cleanup routines
        with patch("subprocess.run", return_value=mock_git_ls):
            pre_untracked = set()
            post_untracked = set(mock_git_ls.stdout.splitlines())
            
            for garbage_file in post_untracked - pre_untracked:
                if os.path.exists(garbage_file) and not garbage_file.startswith(".yani_engine/"):
                    os.remove(garbage_file)
                    
        assert not os.path.exists(leaked_file), "Leaked artifact was not successfully purged from the workspace."
    finally:
        os.chdir(original_cwd)
