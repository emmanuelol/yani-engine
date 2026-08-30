import os
import shutil
import pytest
from unittest.mock import patch

from yani_engine.core.review_ui import batch_diff_review
from yani_engine.core.state import TaskRegistryState


@pytest.mark.asyncio
async def test_batch_diff_review_rejection_restores_and_cleans_tmp(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        os.makedirs(".yani/tmp", exist_ok=True)
        os.makedirs(".yani/rollbacks/T-001/src", exist_ok=True)
        os.makedirs("src", exist_ok=True)

        # 1. Target file before wave was modified
        with open("src/utils.py", "w", encoding="utf-8") as f:
            f.write("MODIFIED REJECTED CONTENT")

        # 2. Original rollback file
        with open(".yani/rollbacks/T-001/src__utils.py", "w", encoding="utf-8") as f:
            f.write("ORIGINAL UNTOUCHED UTILS")

        # 3. Wave temp file
        tmp_file = ".yani/tmp/12345678901234567890123456789012_src__utils.py.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write("MODIFIED REJECTED CONTENT")

        content = """# Memory

## Change Log
| Timestamp | Task ID | Target Path | Summary | Status | Rationale |
|---|---|---|---|---|---|
| 2026-08-29T00:00:00Z | T-001 | src/utils.py | Update utils | planned | refactor |

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Update utils | change | in_progress | worker-1 | none | S-001 | none |

## Task Details
### T-001: Update utils
- **Status**: in_progress
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        # Prompt user with 'N' (Reject all changes)
        with patch("rich.prompt.Prompt.ask", return_value="N"), \
             patch("shutil.which", return_value=None), \
             patch("yani_engine.core.config.config.verbose", True):
            await batch_diff_review([tmp_file])

        # Assert .tmp file is removed
        assert not os.path.exists(tmp_file)

        # Assert original content is restored
        with open("src/utils.py", "r", encoding="utf-8") as f:
            restored = f.read()
        assert restored == "ORIGINAL UNTOUCHED UTILS"

        # Assert task is reset to pending
        tasks = await TaskRegistryState().load_tasks()
        assert tasks["T-001"]["status"] == "pending"
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_batch_diff_review_approval_applies_changes(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        os.makedirs(".yani/tmp", exist_ok=True)
        os.makedirs("src", exist_ok=True)

        tmp_file = ".yani/tmp/12345678901234567890123456789012_src__newfile.py.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write("NEW APPROVED CONTENT")

        content = """# Memory

## Change Log
| Timestamp | Task ID | Target Path | Summary | Status | Rationale |
|---|---|---|---|---|---|
| 2026-08-29T00:00:00Z | T-002 | src/newfile.py | Create new file | planned | feat |

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-002 | Create new file | change | in_progress | worker-1 | none | S-001 | none |

## Task Details
### T-002: Create new file
- **Status**: in_progress
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        # Prompt user with 'Y' (Approve all changes)
        with patch("rich.prompt.Prompt.ask", return_value="Y"), \
             patch("shutil.which", return_value=None), \
             patch("yani_engine.core.config.config.verbose", True):
            await batch_diff_review([tmp_file])

        # Assert .tmp file is renamed / removed
        assert not os.path.exists(tmp_file)

        # Assert target file exists with new content
        assert os.path.exists("src/newfile.py")
        with open("src/newfile.py", "r", encoding="utf-8") as f:
            applied = f.read()
        assert applied == "NEW APPROVED CONTENT"

        # Assert task is marked completed
        tasks = await TaskRegistryState().load_tasks()
        assert tasks["T-002"]["status"] == "completed"
    finally:
        os.chdir(original_cwd)
