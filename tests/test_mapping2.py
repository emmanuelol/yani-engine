import os
from unittest.mock import patch, MagicMock

from yani_engine.core.orchestrator import LLMOrchestrator as YaniEngineCLI

@patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"})
def test_mcp_wrapper_sanitizes_dashes():
    cli = yani_engineCLI()
    cli.mcp_sessions = {"codegraph": MagicMock()}
    
    dummy_tool = MagicMock()
    dummy_tool.name = "codegraph-search"
    
    wrapper = cli._create_mcp_wrapper("codegraph", dummy_tool)
    assert wrapper.__name__ == "codegraph_search", f"Expected codegraph_search, got {wrapper.__name__}"
