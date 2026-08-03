import pytest
import os
import asyncio
from unittest.mock import patch, MagicMock
from dumbledoer.core.state import TaskRegistryState
from dumbledoer.core.orchestrator import LLMOrchestrator as DumbleDoerCLI

@pytest.fixture(autouse=True)
def mock_env_and_gui():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key", "AGY_MODEL": "gemini-3.6-flash"}):
        import dumbledoer.cli.main
        dumbledoer.cli.main.GUI_DIFF_ENABLED = False
        yield

@pytest.mark.asyncio
async def test_schema_compliant_wave_resolution(tmp_path):
    os.chdir(tmp_path)
    
    # Write canonical memory-schema.md format
    with open("memory.md", "w") as f:
        f.write("## Task Registry\n")
        f.write("| Task ID | Title | Type | Status | Owner | Depends On | Session | Checkpoint |\n")
        f.write("| T-001 | A | change | pending | — | none | — | none |\n")
        f.write("| T-002 | B | change | pending | — | T-001 | — | none |\n")
        
    cli = DumbleDoerCLI()
    waves = cli.get_pending_waves()
    
    assert len(waves) == 2
    assert waves[0][0]['id'] == "T-001"
    assert waves[1][0]['id'] == "T-002"
