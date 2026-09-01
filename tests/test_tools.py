import pytest
from unittest.mock import patch, AsyncMock
from yani_engine.core.orchestrator import LLMOrchestrator as YaniEngineCLI


@pytest.mark.asyncio
@patch("yani_engine.core.mcp_manager.connect_mcp", new_callable=AsyncMock)
async def test_orchestrator_tools_registration(mock_connect_mcp):
    cli = YaniEngineCLI()
    await mock_connect_mcp(cli)
    tools = cli.gemini_tools
    tool_names = [getattr(t, "__name__", "") for t in tools]
    assert len(tools) > 0
    assert "read_file" in tool_names
    assert "execute_bash" in tool_names

