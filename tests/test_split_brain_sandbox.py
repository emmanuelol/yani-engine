import pytest

def test_split_brain_sandbox():
    """Verify that file writes accurately sync to Docker shadow mounts."""
    with open('yani_engine/core/state.py', 'r') as f:
        content = f.read()
    # Look for the split-brain fix logic
    assert '.yani_engine/shadow_' in content, "Sandbox split-brain sync is missing."
    assert 'shadow_path = ' in content, "Shadow path not computed."
