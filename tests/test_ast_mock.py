import pytest
from dumbledoer.dumbledoer_cli import ASTMemoryMapper

def test_locate_heading_block_irregular_whitespace():
    mock_memory = """# DumbleDoer Memory

##   TASK rEgistry   

- [ ] T-001: Implement feature
- [ ] T-002: Fix bug

## Change Log
- Done
"""
    # Test targeting '## Task Registry'
    start_idx, end_idx = ASTMemoryMapper.locate_heading_block(mock_memory, "##", "Task Registry")
    
    assert start_idx == 2, f"Expected start_idx=2, got {start_idx}"
    assert end_idx == 7, f"Expected end_idx=7, got {end_idx}"
    
    lines = mock_memory.splitlines()
    block = lines[start_idx:end_idx]
    assert block[0].strip() == "##   TASK rEgistry"
    assert block[3] == "- [ ] T-002: Fix bug"
    print("SUCCESS: Parsing robust against whitespace and case!")
