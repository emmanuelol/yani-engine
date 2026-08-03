import pytest
import asyncio
from unittest.mock import patch, MagicMock
from dumbledoer.core.sandbox import execute_bash

@pytest.mark.asyncio
async def test_native_sandbox_execution():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "native execution success"
        mock_run.return_value = mock_result
        
        result = await execute_bash("echo 'test'", sandbox_mode="native")
        
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "bash"
        assert args[1] == "-c"
        assert "native execution success" in result
