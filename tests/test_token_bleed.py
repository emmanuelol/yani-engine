import pytest
import re

def test_token_bleed():
    """Verify that agent loops are strictly clamped to avoid token bleeds."""
    with open('yani_engine/core/orchestrator.py', 'r') as f:
        content = f.read()
    
    # Verify the clamp fix
    assert 'max_iterations=15' in content, "Agent loop iteration clamping is missing!"
    assert '"medium": 25' in content, "Fallback iteration limits are missing."
