import pytest
import os
import re

def test_token_bleed():
    """Verify that agent loops are strictly clamped to avoid token bleeds."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    target = os.path.join(repo_root, 'yani_engine/core/orchestrator.py')
    with open(target, 'r') as f:
        content = f.read()
    
    # Verify the clamp fix
    assert 'max_iterations=15' in content, "Agent loop iteration clamping is missing!"
    assert '"medium": 25' in content, "Fallback iteration limits are missing."
