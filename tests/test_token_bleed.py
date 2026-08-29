import pytest
import os
import re

def test_token_bleed():
    """Verify that agent loops are strictly clamped to avoid token bleeds.

    The effort→iteration mapping was extracted from orchestrator.py into
    task_executor.py (Phase 5 refactor). The guard is satisfied if the
    clamp exists anywhere in the task execution path.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    # The per-command cap lives in orchestrator.run()
    orchestrator_src = os.path.join(repo_root, "yani_engine/core/orchestrator.py")
    with open(orchestrator_src, "r") as f:
        orch_content = f.read()

    # The per-task effort→iteration map was moved to task_executor.py
    task_exec_src = os.path.join(repo_root, "yani_engine/core/task_executor.py")
    with open(task_exec_src, "r") as f:
        exec_content = f.read()

    assert "max_iterations=15" in orch_content, "Per-command agent loop iteration clamping is missing from orchestrator!"
    assert '"medium": 25' in exec_content, "Fallback effort→iteration limits are missing from task_executor!"
