import pytest
import asyncio
import os
import shutil
from unittest.mock import patch

from dumbledoer.dumbledoer_cli import TaskRegistryState, execute_bash, DumbleDoerCLI

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
| Timestamp | Checkpoint ID | Task ID | Target Path | Action | Status | Rationale |
|---|---|---|---|---|---|---|
| 2026-07-22T00:00:00Z | C-1 | T-1 | file1.txt | modify | planned | Test |
| 2026-07-22T00:00:00Z | C-2 | T-1 | file2.txt | modify | planned | Test |
| 2026-07-22T00:00:00Z | C-3 | T-1 | file3.txt | modify | planned | Test |
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
        await asyncio.to_thread(state._sync_to_markdown, {f"T-1": {"status": f"completed-{i}"}})
        
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
    for i in range(1, 4):
        with open(f".dumbledoer/tmp/C-{i}_file{i}.txt.tmp", "w") as f:
            f.write("new content")
        with open(f"file{i}.txt", "w") as f:
            f.write("old content")
        with open(f".dumbledoer/rollbacks/C-{i}_file{i}.bak", "w") as f:
            f.write("old content")

    cli = DumbleDoerCLI()
    
    with patch("subprocess.run"):
        with patch("rich.prompt.Prompt.ask", side_effect=["S", "file2.txt"]):
            await cli.batch_diff_review([
                ".dumbledoer/tmp/C-1_file1.txt.tmp",
                ".dumbledoer/tmp/C-2_file2.txt.tmp",
                ".dumbledoer/tmp/C-3_file3.txt.tmp"
            ])
            
    with open("memory.md", "r", encoding="utf-8") as f:
        content = f.read()
    
    assert "| C-2 | T-1 | file2.txt | modify | rolled-back |" in content
    assert "| C-1 | T-1 | file1.txt | modify | applied |" in content
    assert "| C-3 | T-1 | file3.txt | modify | applied |" in content
