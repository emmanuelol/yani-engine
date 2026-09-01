import os
from unittest.mock import patch, MagicMock
import pytest

from yani_engine.core.mcp_manager import create_mcp_wrapper
from yani_engine.core.config import config

@pytest.mark.parametrize("raw_tool_name,expected_sanitized_name,input_properties,expected_annotations", [
    (
        "codegraph/impact",
        "codegraph_impact",
        {"query": {"type": "string"}, "limit": {"type": "integer"}},
        {"query": str, "limit": int}
    ),
    (
        "codegraph-search",
        "codegraph_search",
        {"term": {"type": "string"}},
        {"term": str}
    ),
    (
        "context7/search-docs",
        "context7_search_docs",
        {"library": {"type": "string"}, "count": {"type": "integer"}},
        {"library": str, "count": int}
    )
])
@patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"})
def test_mcp_wrapper_sanitization(raw_tool_name, expected_sanitized_name, input_properties, expected_annotations):
    server_prefix = raw_tool_name.split("/")[0].split("-")[0]
    mcp_sessions = {server_prefix: MagicMock()}
    mcp_locks = {}
    
    dummy_tool = MagicMock()
    dummy_tool.name = raw_tool_name
    dummy_tool.inputSchema = {"properties": input_properties} if input_properties is not None else {}
    
    wrapper = create_mcp_wrapper(server_prefix, dummy_tool, mcp_sessions, mcp_locks, config)
    assert wrapper.__name__ == expected_sanitized_name, f"Expected {expected_sanitized_name}, got {wrapper.__name__}"
    assert wrapper.__qualname__ == expected_sanitized_name, f"Expected {expected_sanitized_name}, got {wrapper.__qualname__}"
    
    assert hasattr(wrapper, "__annotations__"), "Wrapper is missing __annotations__"
    for param, expected_type in expected_annotations.items():
        assert param in wrapper.__annotations__
        assert wrapper.__annotations__[param] == expected_type
