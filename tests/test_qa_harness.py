import os
os.environ['GEMINI_API_KEY'] = 'mock'
import pytest
import asyncio
import os
import shutil
from unittest.mock import patch

from yani_engine.core.state import TaskRegistryState
from yani_engine.core.sandbox import execute_bash
from yani_engine.core.orchestrator import LLMOrchestrator as YaniEngineCLI
from yani_engine.core.review_ui import batch_diff_review

@pytest.fixture(autouse=True)
def setup_memory_md():
    initial_content = """# yani_engine Memory
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
    
    os.makedirs(".yani/tmp", exist_ok=True)
    os.makedirs(".yani/rollbacks", exist_ok=True)
    
    yield
    
    if os.path.exists("memory.md"):
        os.remove("memory.md")
    if os.path.exists(".yani"):
        shutil.rmtree(".yani")
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
    os.makedirs(".yani/rollbacks/T-1", exist_ok=True)
    for i in range(1, 4):
        with open(f".yani/tmp/{uuid_base}{i}_file{i}.txt.tmp", "w") as f:
            f.write("new content")
            with open(f"file{i}.txt", "w") as f:
                f.write("new content")
        with open(f".yani/rollbacks/T-1/file{i}.txt", "w") as f:
            f.write("old content")

    cli = YaniEngineCLI()
    
    with patch("subprocess.run"):
        with patch("rich.prompt.Prompt.ask", side_effect=["S", "file2.txt"]):
                with patch("yani_engine.core.orchestrator.config.verbose", True):
                    with patch("yani_engine.cli.main.GUI_DIFF_ENABLED", True, create=True):
                        await batch_diff_review([
                        f".yani/tmp/{uuid_base}1_file1.txt.tmp",
                        f".yani/tmp/{uuid_base}2_file2.txt.tmp",
                        f".yani/tmp/{uuid_base}3_file3.txt.tmp"
                    ])
                    with open("memory.md", "r", encoding="utf-8") as f:
                        content = f.read()

    assert "file2.txt" in content and "rolled-back" in content
    assert "file1.txt" in content and "applied" in content
    assert "file3.txt" in content and "applied" in content
