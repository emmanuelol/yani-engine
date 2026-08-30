import pytest
import os
import asyncio
from yani_engine.core.state import (
    split_markdown_cells,
    format_markdown_cell,
    format_markdown_row,
    MarkdownTable,
    ASTMemoryMapper,
    TaskRegistryState,
    update_task_registry_row,
    flush_task_registry,
    register_task_batch,
)


def test_split_and_format_markdown_cells_pipe_bomb():
    # 1. Pipe in inline code block
    raw_line = "| T-001 | `val | other` | change | pending | — | none | — | none |"
    cells = split_markdown_cells(raw_line)
    assert len(cells) == 8
    assert cells[0] == "T-001"
    assert cells[1] == "`val | other`"
    assert cells[2] == "change"

    # 2. Escaped pipe in cell
    raw_line_escaped = r"| T-002 | Pipe \| in title | change | pending | — | none | — | none |"
    cells_escaped = split_markdown_cells(raw_line_escaped)
    assert len(cells_escaped) == 8
    assert cells_escaped[1] == "Pipe | in title"

    # 3. Format row with unescaped pipes and newlines
    title_with_pipes = "Fix A | B | C with\nmultiline"
    row = format_markdown_row(["T-003", title_with_pipes, "change", "pending", "—", "none", "—", "none"])
    parsed = split_markdown_cells(row)
    assert len(parsed) == 8
    assert parsed[0] == "T-003"
    assert parsed[1] == "Fix A | B | C with<br>multiline"


def test_markdown_table_crud_parser():
    table_lines = [
        "## Some Header",
        "Random text",
        "| Task ID | Title | Status | Owner |",
        "|---|---|---|---|",
        "| T-001 | Fix auth | pending | — |",
        "| T-002 | `parse | ast` | completed | worker-1 |",
        "Random footer paragraph",
    ]
    table = MarkdownTable(table_lines)
    assert table.headers == ["Task ID", "Title", "Status", "Owner"]
    assert table.get_column_index("Task ID") == 0
    assert table.get_column_index("Status") == 2
    assert len(table.rows) == 2
    assert table.rows[0][1][0] == "T-001"
    assert table.rows[1][1][1] == "`parse | ast`"


@pytest.mark.asyncio
async def test_append_to_markdown_table_with_trailing_paragraph(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        content = """# Memory

## Change Log
| Timestamp | Task ID | Target Path | Summary | Status | Rationale |
|---|---|---|---|---|---|
| 2026-08-29T00:00:00 | T-001 | main.py | init | applied | bootstrap |

This is a trailing paragraph inside Change Log that previously broke appending.

## Next Section
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        new_row = format_markdown_row(["2026-08-29T01:00:00", "T-002", "app.py", "update", "applied", "feat"])
        success = ASTMemoryMapper.append_to_markdown_table("memory.md", "Change Log", new_row)
        assert success

        with open("memory.md", "r", encoding="utf-8") as f:
            updated = f.read()

        # The new row must be placed directly after the first table row, NOT below the trailing paragraph
        lines = updated.splitlines()
        row_1_idx = next(i for i, l in enumerate(lines) if "T-001" in l)
        row_2_idx = next(i for i, l in enumerate(lines) if "T-002" in l)
        paragraph_idx = next(i for i, l in enumerate(lines) if "This is a trailing paragraph" in l)

        assert row_2_idx == row_1_idx + 1
        assert paragraph_idx > row_2_idx
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_register_task_batch_with_pipe_and_code_blocks(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        memory_content = (
            "# Memory\n\n"
            "## Task Registry\n"
            "| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |\n"
            "|---|---|---|---|---|---|---|---|\n\n"
            "## Archive Index\n"
            "| Task ID | Title | Category | Owner | Session | Archive File |\n"
            "|---|---|---|---|---|---|\n\n"
            "## Task Details\n"
        )
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(memory_content)

        tasks = [
            {
                "title": "[Core] Implement `a | b` bitwise logic",
                "task_type": "change",
                "deps": "none",
                "description": "Handle bitwise OR and logical || operators",
                "outputs": "core/math.py",
                "success_criteria": "Tests pass",
                "estimated_effort": "small",
            }
        ]

        result = await register_task_batch(tasks)
        assert "Successfully registered tasks" in result

        state = TaskRegistryState()
        loaded = state._load_tasks_unlocked()
        assert "T-001" in loaded
        assert loaded["T-001"]["title"] == "[Core] Implement `a | b` bitwise logic"
        assert loaded["T-001"]["status"] == "pending"

        # Update and flush
        await update_task_registry_row("T-001", "in_progress", "worker-1")
        await flush_task_registry()

        loaded_after = state._load_tasks_unlocked()
        assert loaded_after["T-001"]["status"] == "in_progress"
        assert loaded_after["T-001"]["owner"] == "worker-1"
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_archiver_with_escaped_pipe_cells(tmp_path):
    from yani_engine.core.archiver import archive_stale_sessions

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        content = """# Memory

## Config
archive_keep_sessions: 1

## Session Log
| Session ID | Start Time | End Time | Tasks Claimed | Outcome |
|---|---|---|---|---|
| S-001 | 2026-08-29T00:00:00Z | 2026-08-29T01:00:00Z | T-001 | completed |
| S-002 | 2026-08-29T01:00:00Z | 2026-08-29T02:00:00Z | T-002 | in_progress |

## Change Log
| Timestamp | Task ID | Target Path | Summary | Status | Rationale |
|---|---|---|---|---|---|
| 2026-08-29T00:00:00Z | T-001 | file.py | Added `a | b` logic | applied | feat |

## Checkpoint Registry
| Checkpoint ID | Task ID | Step | Session ID | Files Snapshotted |
|---|---|---|---|---|
| chk_1 | T-001 | step1 | S-001 | file.py |

## Task Details
### T-001: Implement logic
- **Status**: completed
- **Owner**: worker-1
- **Assigned Session**: S-001
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        # S-001 is terminal, S-002 is active -> Keep window 1 means S-001 should be archived if we have > 1 terminal session.
        # Let's make S-002 also completed to trigger archival of S-001
        content_two_term = content.replace("in_progress", "completed")
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content_two_term)

        await archive_stale_sessions()

        assert os.path.exists(".yani/archive/S-001.md")
        with open(".yani/archive/S-001.md", "r", encoding="utf-8") as f:
            archive_data = f.read()
        assert "outcome: completed" in archive_data
        assert "file.py" in archive_data

        with open("memory.md", "r", encoding="utf-8") as f:
            mem = f.read()
        assert "(archived)" in mem
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_append_session_log_row_schema_alignment(tmp_path):
    from yani_engine.core.state import append_session_log_row

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        content = """# Memory

## Session Log
| Session ID | Start Time | End Time | Tasks Claimed | Outcome |
|---|---|---|---|---|
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        msg = await append_session_log_row("S-001", "T-001")
        assert "Session S-001 logged" in msg

        with open("memory.md", "r", encoding="utf-8") as f:
            updated = f.read()

        lines = [l.strip() for l in updated.splitlines() if l.strip().startswith("|") and "---" not in l and "Session ID" not in l]
        assert len(lines) == 1
        cells = split_markdown_cells(lines[0])
        assert len(cells) == 5
        assert cells[0] == "S-001"
        assert cells[3] == "T-001"
        assert cells[4] == "in_progress"
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_handlers_status_archive_index_lookup(tmp_path, capsys):
    from unittest.mock import MagicMock
    from yani_engine.commands.handlers import handle_status

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        content = """# Memory

## Project Goal
Test Status Display

## Session Log
| Session ID | Start Time | End Time | Tasks Claimed | Outcome |
|---|---|---|---|---|
| S-001 | 2026-08-29T00:00:00Z | 2026-08-29T01:00:00Z | T-001 | completed (archived) |

## Archive Index
| Session ID | Archived At | Archive File | Tasks Archived | Outcome |
|---|---|---|---|---|
| S-001 | 2026-08-29T01:00:00Z | .yani/archive/S-001.md | 1 | completed |

## Task Registry
| Task ID | Title | Type | Status | Owner | Depends On | Assigned Session | Checkpoint |
|---|---|---|---|---|---|---|---|
| T-001 | Feature A | change | completed | worker-1 | none | S-001 | archived |

## Task Details
"""
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write(content)

        mock_orch = MagicMock()
        mock_orch.budget_manager.estimated_tokens = 500
        mock_orch.budget_manager.budget_limit = 100000

        await handle_status(mock_orch, ["-v"])
        captured = capsys.readouterr().out

        assert "[Archived] Task details moved to .yani/archive/S-001.md" in captured
        assert "moved to completed" not in captured
    finally:
        os.chdir(original_cwd)
