"""
archiver.py — Stateless Session Archival module.

Extracted from LLMOrchestrator._archive_stale_sessions to decouple
Markdown DOM manipulation and filesystem archival logic from the core
execution engine.

Concurrency contract:
  - memory.md reads are guarded by _MEMORY_MUTEX + get_registry_lock().
  - memory.md writes use the same double-lock at the final atomic swap.
  - archive file writes use get_registry_lock() only (archive files are
    session-unique, so _MEMORY_MUTEX is not required there).
  - os.makedirs / os.replace are wrapped in asyncio.to_thread() to avoid
    blocking the event loop during slow disk I/O.

Lock topology is preserved verbatim from the original method to prevent
introducing new deadlock surfaces.
"""

import os
import re
import asyncio
from datetime import datetime, timezone

from yani_engine.core.locks import _MEMORY_MUTEX, get_registry_lock
from yani_engine.core.state import ASTMemoryMapper, split_markdown_cells, format_markdown_row


async def archive_stale_sessions() -> None:
    """
    Scans the Session Log in memory.md, identifies terminal sessions
    (completed / error / interrupted) beyond the configured keep window,
    and moves their log rows + task details to individual archive files
    under .yani/archive/.

    The archival is idempotent: sessions already marked "(archived)" in
    memory.md are ignored. If fewer sessions than `archive_keep_sessions`
    are terminal, the function exits early without touching the filesystem.
    """
    archive_keep_sessions = 1

    if not os.path.exists("memory.md"):
        return

    # --- Phase 1: Read memory.md under full lock ---
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            with open("memory.md", "r", encoding="utf-8") as f:
                content = f.read()

    # --- Phase 2: Parse Config block for retention setting ---
    config_start, config_end = ASTMemoryMapper.locate_heading_block(content, "##", "Config")
    if config_start != -1:
        for line in content.splitlines()[config_start:config_end]:
            if "archive_keep_sessions:" in line:
                try:
                    archive_keep_sessions = int(line.split(":")[1].strip())
                except Exception:
                    pass

    # --- Phase 3: Locate Section Boundaries ---
    sess_start, sess_end = ASTMemoryMapper.locate_heading_block(content, "##", "Session Log")
    if sess_start == -1:
        return

    # --- Phase 4: Identify Terminal Sessions ---
    lines = content.splitlines()
    session_log_lines = lines[sess_start + 1 : sess_end]

    terminal_sessions = []
    for i, line in enumerate(session_log_lines):
        if (
            line.strip().startswith("|")
            and "---" not in line
            and "Timestamp" not in line
            and "Session ID" not in line
        ):
            parts = split_markdown_cells(line)
            if len(parts) >= 5:
                sid = parts[0]
                outcome = parts[4].lower()
                if outcome in ("completed", "error") or (
                    outcome.startswith("interrupted-") and not outcome.endswith("(archived)")
                ):
                    terminal_sessions.append((sid, line, i))

    if len(terminal_sessions) <= archive_keep_sessions:
        return

    to_archive = terminal_sessions[:-archive_keep_sessions]
    if not to_archive:
        return

    # --- Phase 4: Ensure archive directories exist (non-blocking) ---
    await asyncio.to_thread(os.makedirs, ".yani/archive", exist_ok=True)
    await asyncio.to_thread(os.makedirs, ".yani/tmp", exist_ok=True)

    # --- Phase 5: Parse Task Details block into per-task line buckets ---
    ASTMemoryMapper.locate_heading_block(content, "##", "Task Details")  # side-effect check

    tasks: dict[str, list[str]] = {}
    current_task: str | None = None
    current_lines: list[str] = []

    in_code_block = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block

        if not in_code_block and re.match(r"^###\s+(T-[\w\-]+)", line):
            if current_task:
                tasks[current_task] = current_lines
            current_task = re.match(r"^###\s+(T-[\w\-]+)", line).group(1)
            current_lines = [line]
        elif current_task:
            if not in_code_block and re.match(r"^#+\s+", line):
                tasks[current_task] = current_lines
                current_task = None
            else:
                current_lines.append(line)
    if current_task:
        tasks[current_task] = current_lines

    # --- Phase 6: Map sessions → tasks they own ---
    archived_tasks_per_session: dict[str, list[str]] = {}
    for sid, line, _ in to_archive:
        archived_tasks: list[str] = []
        for tid, tlines in tasks.items():
            status = "pending"
            assigned = "none"
            for tline in tlines:
                if tline.startswith("- **Status**:"):
                    status = tline.split(":", 1)[1].strip()
                elif tline.startswith("- **Assigned Session**:"):
                    assigned = tline.split(":", 1)[1].strip()
            if assigned == sid and status in ("completed", "error", "deferred", "abandoned"):
                archived_tasks.append(tid)
        archived_tasks_per_session[sid] = archived_tasks

    # --- Phase 7: Build archive files and mutate new_lines in-place ---
    new_lines = list(lines)

    for sid, sess_line, _ in to_archive:
        sess_cells = split_markdown_cells(sess_line)
        sess_outcome = sess_cells[4] if len(sess_cells) > 4 else "unknown"
        record_lines = [
            f"# Archived Session: {sid}",
            "",
            f"session_id: {sid}",
            f"archived_at: {datetime.now(timezone.utc).isoformat()}",
            f"outcome: {sess_outcome}",
            "source: memory.md",
            "",
            "## Session Log Entry",
            "| Session ID | Start Time | End Time | Tasks Claimed | Outcome |",
            "|---|---|---|---|---|",
            sess_line,
            "",
            "## Change Log Entries",
            "| Timestamp | Task ID | Target Path | Summary | Status | Rationale |",
            "|---|---|---|---|---|---|",
        ]

        chg_start, chg_end = ASTMemoryMapper.locate_heading_block(content, "##", "Change Log")
        if chg_start != -1:
            for j in range(chg_start + 1, chg_end):
                if (
                    lines[j].strip().startswith("|")
                    and "---" not in lines[j]
                    and "Timestamp" not in lines[j]
                ):
                    parts = split_markdown_cells(lines[j])
                    if len(parts) >= 5:
                        tid = parts[1]
                        if tid in archived_tasks_per_session[sid] or tid == sid:
                            record_lines.append(lines[j])
                            new_lines[j] = ""

        record_lines.append("")
        record_lines.append("## Checkpoint Registry Entries")
        record_lines.append(
            "| Checkpoint ID | Task ID | Step | Session ID | Files Snapshotted |"
        )
        record_lines.append("|---|---|---|---|---|")

        chk_start, chk_end = ASTMemoryMapper.locate_heading_block(
            content, "##", "Checkpoint Registry"
        )
        if chk_start != -1:
            for j in range(chk_start + 1, chk_end):
                if (
                    lines[j].strip().startswith("|")
                    and "---" not in lines[j]
                    and "Checkpoint ID" not in lines[j]
                ):
                    parts = split_markdown_cells(lines[j])
                    if len(parts) >= 4:
                        csid = parts[3]
                        if csid == sid:
                            record_lines.append(lines[j])
                            new_lines[j] = ""

        record_lines.append("")
        record_lines.append("## Task Details")

        for tid in archived_tasks_per_session[sid]:
            record_lines.extend(tasks[tid])
            t_idx = -1
            for k, nl in enumerate(new_lines):
                if nl == f"### {tid}":
                    t_idx = k
                    break
            if t_idx != -1:
                while t_idx < len(new_lines) and (
                    new_lines[t_idx] == f"### {tid}"
                    or not re.match(r"^#+\s+", new_lines[t_idx])
                ):
                    new_lines[t_idx] = ""
                    t_idx += 1
                    if t_idx < len(new_lines) and re.match(r"^#+\s+", new_lines[t_idx]):
                        break

        # Write the archive file atomically via tmp → final rename
        archive_tmp = f".yani/tmp/{sid}.archive.tmp"
        archive_md = f".yani/archive/{sid}.md"
        async with get_registry_lock():
            with open(archive_tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(record_lines))
        await asyncio.to_thread(os.replace, archive_tmp, archive_md)

        # Update or create Archive Index in new_lines
        idx_start, idx_end = ASTMemoryMapper.locate_heading_block(content, "##", "Archive Index")
        archive_row = format_markdown_row([
            sid,
            datetime.now(timezone.utc).isoformat(),
            f".yani/archive/{sid}.md",
            len(archived_tasks_per_session[sid]),
            sess_outcome,
        ])
        if idx_start == -1:
            new_lines.append("")
            new_lines.append("## Archive Index")
            new_lines.append("| Session ID | Archived At | Archive File | Tasks Archived | Outcome |")
            new_lines.append("|---|---|---|---|---|")
            new_lines.append(archive_row)
        else:
            new_lines.insert(idx_end, archive_row)

        # Mark session row as archived in the Session Log
        for j in range(sess_start + 1, sess_end):
            cells = split_markdown_cells(new_lines[j])
            if cells and cells[0] == sid:
                if len(cells) > 4:
                    cells[4] = f"{cells[4]} (archived)"
                new_lines[j] = format_markdown_row(cells)
                break

    # --- Phase 8: Atomic write of pruned memory.md ---
    final_lines = [l for l in new_lines if l != ""]
    tmp_mem = ".yani/tmp/memory.md.tmp"
    async with _MEMORY_MUTEX:
        async with get_registry_lock():
            with open(tmp_mem, "w", encoding="utf-8") as f:
                f.write("\n".join(final_lines))
            os.replace(tmp_mem, "memory.md")

    trimmed = len(lines) - len(final_lines)
    print(
        f"Archived {len(to_archive)} session(s) → .yani/archive/ "
        f"({trimmed} lines trimmed from memory.md)"
    )
