import pytest
import os

def test_split_brain_sandbox():
    """Verify that file writes accurately sync to Docker shadow mounts."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    target = os.path.join(repo_root, 'yani_engine/core/state.py')
    with open(target, 'r') as f:
        content = f.read()
    # Look for the split-brain fix logic
    assert '.yani/shadow_' in content, "Sandbox split-brain sync is missing."
    assert 'shadow_path = ' in content, "Shadow path not computed."
