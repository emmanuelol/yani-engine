import json
import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace

from yani_engine.core.llm_provider import LocalProvider, LocalResponse, MockUsage


def test_local_provider_parse_tool_calls_malformed_json():
    provider = LocalProvider(base_url="http://localhost:11434/v1")

    # 1. Invalid JSON string in arguments
    msg_malformed = {
        "content": "",
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": '{"path": "file.py", "content": UNQUOTED_CORRUPTED_JSON',
                },
            }
        ],
    }
    resp = LocalResponse(msg_malformed, MockUsage(100))
    calls = provider.parse_tool_calls(resp)
    assert len(calls) == 1
    assert calls[0]["id"] == "call_123"
    assert calls[0]["name"] == "write_file"
    assert calls[0]["args"] == {}  # Gracefully fallback to empty dict

    # 2. Arguments is a JSON list instead of dict
    msg_list = {
        "content": "",
        "tool_calls": [
            {
                "id": "call_456",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '["not", "a", "dict"]',
                },
            }
        ],
    }
    resp2 = LocalResponse(msg_list, MockUsage(50))
    calls2 = provider.parse_tool_calls(resp2)
    assert len(calls2) == 1
    assert calls2[0]["args"] == {}

    # 3. Arguments already a dict
    msg_dict = {
        "content": "",
        "tool_calls": [
            {
                "id": "call_789",
                "type": "function",
                "function": {
                    "name": "execute_bash",
                    "arguments": {"command": "ls -la"},
                },
            }
        ],
    }
    resp3 = LocalResponse(msg_dict, MockUsage(20))
    calls3 = provider.parse_tool_calls(resp3)
    assert len(calls3) == 1
    assert calls3[0]["args"] == {"command": "ls -la"}


def test_local_provider_format_tool_response():
    provider = LocalProvider(base_url="http://localhost:11434/v1")
    resp = provider.format_tool_response("read_file", "File contents here", call_id="call_001")
    assert resp["role"] == "tool"
    assert resp["name"] == "read_file"
    assert resp["content"] == "File contents here"
    assert resp["tool_call_id"] == "call_001"

    err = provider.format_tool_error("read_file", "File not found", call_id="call_002")
    assert err["role"] == "tool"
    assert err["name"] == "read_file"
    assert "Error: File not found" in err["content"]
    assert err["tool_call_id"] == "call_002"
