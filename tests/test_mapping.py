import os
from unittest.mock import patch, MagicMock

from dumbledoer.dumbledoer_cli import DumbleDoerCLI

@patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"})
def test_mcp_wrapper_sanitizes_slashes():
    cli = DumbleDoerCLI()
    cli.mcp_sessions = {"codegraph": MagicMock()}
    
    dummy_tool = MagicMock()
    dummy_tool.name = "codegraph/impact"
    dummy_tool.inputSchema = {
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"}
        }
    }
    
    wrapper = cli._create_mcp_wrapper("codegraph", dummy_tool)
    assert wrapper.__name__ == "codegraph_impact", f"Expected codegraph_impact, got {wrapper.__name__}"
    assert wrapper.__qualname__ == "codegraph_impact", f"Expected codegraph_impact, got {wrapper.__qualname__}"
    
    assert hasattr(wrapper, "__annotations__"), "Wrapper is missing __annotations__"
    assert "query" in wrapper.__annotations__
    assert wrapper.__annotations__["query"] == str
    assert "limit" in wrapper.__annotations__
    assert wrapper.__annotations__["limit"] == int
