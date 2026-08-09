import os
os.environ['GEMINI_API_KEY'] = 'mock'
import pytest
import asyncio
import os
import shutil
from unittest.mock import patch

from dumbledoer.core.state import TaskRegistryState
from dumbledoer.core.sandbox import execute_bash
from dumbledoer.core.orchestrator import LLMOrchestrator as DumbleDoerCLI

@pytest.fixture(autouse=True)
def setup_memory_md():
    initial_content = """# DumbleDoer Memory
## Config
- sandbox_mode: native

## Task Registry
| Task ID | Description | Status |
|---|---|---|
| T-1 | Test | pending |

## Change Log
| Timestamp | Task ID | Target Path | Summary | Status | Rationale |
|---|---|---|---|---|---|
| 2026-07-22T00:00:00Z | T-1 | file1.txt | modify | planned | Test |
| 2026-07-22T00:00:00Z | T-1 | file2.txt | modify | planned | Test |
| 2026-07-22T00:00:00Z | T-1 | file3.txt | modify | planned | Test |
"""
    with open("memory.md", "w", encoding="utf-8") as f:
        f.write(initial_content)
    
    os.makedirs(".dumbledoer/tmp", exist_ok=True)
    os.makedirs(".dumbledoer/rollbacks", exist_ok=True)
    
    yield
    
    if os.path.exists("memory.md"):
        os.remove("memory.md")
    if os.path.exists(".dumbledoer"):
        shutil.rmtree(".dumbledoer")
    for f in ["file1.txt", "file2.txt", "file3.txt"]:
        if os.path.exists(f):
            os.remove(f)

@pytest.mark.asyncio
async def test_suite_1_ledger_sync_lock():
    state = TaskRegistryState()
    
    async def sync_task(i):
        await state._sync_to_markdown({f"T-1": {"status": f"completed-{i}"}})
        
    async def bash_task(i):
        await execute_bash("echo 'ok'")
        
    tasks = []
    for i in range(100):
        tasks.append(sync_task(i))
    for i in range(50):
        tasks.append(bash_task(i))
        
    await asyncio.gather(*tasks)
    
    with open("memory.md", "r", encoding="utf-8") as f:
        content = f.read()
    
    assert "## Task Registry" in content
    assert "## Config" in content
    assert content.count("## Change Log") == 1

@pytest.mark.asyncio
async def test_suite_2_orphan_recovery():
    uuid_base = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d"
    for i in range(1, 4):
        with open(f".dumbledoer/tmp/{uuid_base}{i}_file{i}.txt.tmp", "w") as f:
            f.write("new content")
            with open(f"file{i}.txt", "w") as f:
                f.write("new content")
        with open(f".dumbledoer/rollbacks/{uuid_base}{i}_file{i}.txt.bak", "w") as f:
            f.write("old content")

    cli = DumbleDoerCLI()
    
    with patch("subprocess.run"):
        with patch("rich.prompt.Prompt.ask", side_effect=["S", "file2.txt"]):
            with patch("dumbledoer.core.orchestrator.config.verbose", True):
                with patch("dumbledoer.cli.main.GUI_DIFF_ENABLED", True, create=True):
                    await cli.batch_diff_review([
                    f".dumbledoer/tmp/{uuid_base}1_file1.txt.tmp",
                    f".dumbledoer/tmp/{uuid_base}2_file2.txt.tmp",
                    f".dumbledoer/tmp/{uuid_base}3_file3.txt.tmp"
                ])
                with open("memory.md", "r", encoding="utf-8") as f:
                    content = f.read()

    assert "| T-1 | file2.txt | modify | rolled-back |" in content
    assert "| T-1 | file1.txt | modify | applied |" in content
    assert "| T-1 | file3.txt | modify | applied |" in content
