import os
import shutil
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from yani_engine.core.sandbox import _ensure_warm_sandbox, _cleanup_all_sandboxes
from yani_engine.core.state import register_task_batch, update_task_registry_row


@pytest.mark.asyncio
async def test_pydantic_error_truncation_exact_message():
    """Verify that oversized invalid arguments produce a concise truncated error under 1600 chars."""
    huge_task = [
        {
            "id": "INVALID_" + ("A" * 30000),
            "title": "Title",
            "task_type": "change",
        }
    ]
    res = await register_task_batch(huge_task)
    assert "State mutation rejected: Invalid arguments" in res
    assert "[TRUNCATED: Payload too large. Ensure descriptions are concise.]" in res
    assert len(res) <= 1600


@pytest.mark.asyncio
@patch("subprocess.run")
async def test_worktree_branch_cleanup_on_manual_yani_deletion(mock_run, tmp_path):
    """Verify that _ensure_warm_sandbox prunes worktrees and deletes the branch unconditionally."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        # Configure mock return values
        def fake_run(cmd, *args, **kwargs):
            res = MagicMock()
            res.returncode = 0
            if "rev-parse" in cmd:
                res.stdout = "true"
            elif "docker" in cmd and "ps" in cmd:
                res.stdout = ""
            elif "docker" in cmd and "inspect" in cmd:
                res.stdout = "true"
            else:
                res.stdout = ""
            return res

        mock_run.side_effect = fake_run

        active_id = "test-worker-resilience"
        success = await _ensure_warm_sandbox(worker_id=active_id)
        assert success is True

        # Verify git worktree prune was invoked before or during setup
        prune_calls = [
            c for c in mock_run.call_args_list if c[0][0][:3] == ["git", "worktree", "prune"]
        ]
        assert len(prune_calls) >= 1

        # Verify branch deletion was invoked unconditionally
        branch_del_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][:4] == ["git", "branch", "-D", f"yani-worker-{active_id}"]
        ]
        assert len(branch_del_calls) >= 1
    finally:
        os.chdir(original_cwd)
