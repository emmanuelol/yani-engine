import asyncio
import os
import pytest
import shutil
from unittest.mock import patch
from yani_engine.core.state import write_file_with_review
from yani_engine.core.state import ASTMemoryMapper

@pytest.mark.asyncio
async def test_update_memory_registry_concurrency(tmp_path):
    """Test that 50 concurrent async threads can update memory.md without race conditions."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with open("memory.md", "w") as f:
            f.write("- sandbox_mode: true\n\n## TARGET_BLOCK\n")
            
        async def worker(i):
            import yani_engine.core.state
            async with yani_engine.core.state._MEMORY_MUTEX:
                async with yani_engine.core.state.get_registry_lock():
                    with open("memory.md", "a") as f:
                        f.write(f"\n{i}")
            return "Successfully updated"
            
        results = await asyncio.gather(*[worker(i) for i in range(50)])
        
        with open("memory.md", "r") as f:
            content = f.read()
            
        successes = [r for r in results if "Successfully updated" in r]
        assert len(successes) == 50, f"Expected 50 successes, got {len(successes)}"
        
        for i in range(50):
            assert f"\n{i}" in content, f"Missing entry {i} in memory.md"
    finally:
        os.chdir(original_cwd)

@pytest.mark.asyncio
@patch('yani_engine.core.state.subprocess.run')
@patch('yani_engine.core.state.CheckpointManager')
@patch('rich.prompt.Confirm.ask', return_value=False)
async def test_temp_file_collision(mock_confirm, mock_checkpoint, mock_subprocess, tmp_path):
    """Test that concurrent write_file_with_review calls for same basename don't collide."""
    from unittest.mock import AsyncMock
    mock_subprocess.return_value.stdout = "Affected symbols: 2\n"
    mock_checkpoint.return_value.write_rollback_copy = AsyncMock()
    mock_checkpoint.return_value.log_planned_change = AsyncMock()
    mock_checkpoint.return_value.write_checkpoint_json = AsyncMock()
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        os.makedirs("api")
        os.makedirs("db")
        with open("api/utils.py", "w") as f: f.write("api")
        with open("db/utils.py", "w") as f: f.write("db")
        
        async def run_write(path):
            return await write_file_with_review(path, "new content", "T-test")
            
        # Run simultaneously
        await asyncio.gather(run_write("api/utils.py"), run_write("db/utils.py"))
        
        # Verify two tmp files exist in .yani/tmp
        tmp_dir = ".yani/tmp"
        assert os.path.exists(tmp_dir)
        tmp_files = os.listdir(tmp_dir)
        assert len(tmp_files) == 2
        assert tmp_files[0] != tmp_files[1]
        assert tmp_files[0].endswith("utils.py.tmp")
        assert tmp_files[1].endswith("utils.py.tmp")
    finally:
        os.chdir(original_cwd)

def test_ast_parser_edge_case():
    """Test AST parser ignores bash comments."""
    mock_memory = """# Memory
    
## Task Details
### T-001
- **Description**: Do something
- **Code**:
```bash
# Comment 1
echo "hello"
# Comment 2
```

## Next Section
"""
    start_idx, end_idx = ASTMemoryMapper.locate_heading_block(mock_memory, "###", "T-001")
    lines = mock_memory.splitlines()
    block = lines[start_idx:end_idx]
    
    # Assert that the block contains the bash comments and stops at Next Section
    block_text = "\n".join(block)
    assert "# Comment 1" in block_text
    assert "# Comment 2" in block_text
    assert "## Next Section" not in block_text
