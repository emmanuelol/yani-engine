import pytest
import json
import os
from unittest.mock import patch, AsyncMock, MagicMock
from dumbledoer.core.orchestrator import LLMOrchestrator
from dumbledoer.core.config import config
from dumbledoer.core.state import register_task_batch

@pytest.mark.asyncio
async def test_iterate_tool_whitelist():
    """Verify that iterate allows register_task_batch but strictly blocks the deprecated add_task tool."""
    orch = LLMOrchestrator()
    tools = orch._get_tools_for_command("iterate")
    tool_names = [getattr(t, "__name__", "") for t in tools]
    
    assert "register_task_batch" in tool_names, "register_task_batch must be available to iterate."
    assert "add_task" not in tool_names, "add_task MUST be blocked to prevent single-task hallucination loops."

@pytest.mark.asyncio
async def test_iterate_manifest_options():
    """Verify the iterate.json manifest exposes the required prompt and enrich options to the overarching client."""
    manifest_path = "commands/iterate.json"
    assert os.path.exists(manifest_path), "iterate.json manifest must exist."
    
    with open(manifest_path, "r") as f:
        data = json.load(f)
        
    assert "options" in data, "iterate command must expose options to the client."
    option_names = [opt["name"] for opt in data["options"]]
    assert "prompt" in option_names, "Prompt parameter is missing from the manifest."
    assert "enrich" in option_names, "Enrich parameter is missing from the manifest."

@pytest.mark.asyncio
@patch("dumbledoer.core.orchestrator.LLMOrchestrator._get_sliced_memory", new_callable=AsyncMock)
async def test_iterate_memory_slicing_token_clamp(mock_sliced_memory):
    """Verify that iterate does NOT request the token-heavy 'Task Details' section."""
    orch = LLMOrchestrator()
    
    # Mock the read_file tool to provide a fake SYSTEM_INSTRUCTIONS.md to pass the setup
    async def mock_read_file(path, **kwargs):
        return "mock content"
    orch.local_tools[0] = mock_read_file
    
    mock_sliced_memory.return_value = "Mocked Memory Slice"
    
    await orch._get_system_instructions(command="iterate", task_id=None)
    
    # Check the exact array passed to _get_sliced_memory
    mock_sliced_memory.assert_called_once()
    requested_sections = mock_sliced_memory.call_args[0][0]
    
    assert "Task Details" not in requested_sections, "CRITICAL: Task Details must be excluded to prevent token bleed."
    assert "Task Registry" in requested_sections, "Task Registry must be included for context."

@pytest.mark.asyncio
@patch("dumbledoer.core.state.ASTMemoryMapper")
@patch("builtins.open", new_callable=MagicMock)
async def test_register_task_batch_soft_warnings(mock_open, mock_mapper):
    """Verify that poorly formatted tasks trigger soft warnings and auto-patching rather than hard failures."""
    
    # Mocking the AST mapper to return valid block indices
    mock_mapper.locate_heading_block.side_effect = [
        (10, 20),  # Task Registry
        (30, 40),  # Archive Index
        (50, 60),  # Task Details
        (10, 20)   # Task Registry (new)
    ]
    
    # Provide a mock memory.md content
    mock_file = MagicMock()
    mock_file.read.return_value = "## Task Registry\n\n## Archive Index\n\n## Task Details\n"
    mock_file.__enter__.return_value = mock_file
    mock_open.return_value = mock_file
    
    malformed_tasks = [
        {
            "title": "Fix the database login error", # Missing [Category]
            "task_type": "change",
            "deps": "none",
            "description": "Fix it.",
            "outputs": "db/auth.py, db/models.py, api/routes.py, ui/login.js", # > 2 files
            "estimated_effort": "small" # Atomicity violation
        }
    ]
    
    # Capture print statements to verify the soft warnings fired
    with patch("builtins.print") as mock_print:
        result = await register_task_batch(malformed_tasks)
        
    assert "Successfully registered tasks" in result, "The batch registration should succeed despite the warnings."
    
    # Verify the title was auto-patched
    assert malformed_tasks[0]["title"] == "[Uncategorized] Fix the database login error", "The title was not auto-patched."
    
    # Verify warnings were logged to stdout
    print_calls = [call.args[0] for call in mock_print.call_args_list]
    assert any("missing [Category] tag" in msg for msg in print_calls), "Category soft warning did not fire."
    assert any("assigned 4 files to a 'small' effort tier" in msg for msg in print_calls), "Atomicity soft warning did not fire."
