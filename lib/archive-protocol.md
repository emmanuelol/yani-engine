# archive-protocol: Session Archiving and Retrieval

Bounds `memory.md` growth by moving completed sessions' detailed history into
per-session archive records under `.dumbledoer/archive/`. Loaded lazily:
at session close (start/execute/resume/iterate) and at archived-record
retrieval (report/rollback/status).

---

## Trigger (run at every session close, after the Session Log row is finalized)

1. List sessions whose Session Log outcome is terminal: `completed`, `error`,
   or any `interrupted-*` outcome that has been superseded by a newer session.
2. Exclude:
   - the **`archive_keep_sessions` most recent** terminal sessions (Config key,
     optional; default **1** — the most recent terminal session always stays as
     working context), and
   - any session referenced as `Owner` by a task whose status is not terminal
     (`completed`/`deferred`).
3. Archive the remaining sessions, **oldest first**, one at a time using the
   interruption-safety protocol below. If none remain, do nothing (silent).
4. After archiving, report: `Archived {N} session(s) → .dumbledoer/archive/ ({M} lines trimmed from memory.md)`.

**Task-archival rule**: a task is archived with session S iff its status is
terminal AND S is the most recent session in its Owner / Assigned Session
history. Non-terminal tasks always stay in `memory.md` in full.

---

## Archive record format (`.dumbledoer/archive/{sessionId}.md`)

```markdown
# Archived Session: {sessionId}

session_id: {sessionId}
archived_at: {ISO 8601}
outcome: {original Session Log outcome}
source: memory.md

## Session Log Entry
{original row, verbatim, with table header}

## Change Log Entries
{all rows whose Task ID is archived with this session, verbatim}

## Checkpoint Registry Entries
{all rows whose Session ID is this session, verbatim}

## Task Details
{full `### T-NNN:` subsections for each task archived with this session}
```

The file name MUST equal the `session_id` it contains. A task's Details
subsection may live in exactly one archive record.

---

## Interruption-safety protocol (4 steps, mandatory order)

```
1. Write the archive record to .dumbledoer/tmp/{sessionId}.archive.tmp
2. Verify it: parses as Markdown, contains all five sections, task subsection
   count matches the task-archival rule's selection
3. Atomic rename → .dumbledoer/archive/{sessionId}.md
4. Rewrite memory.md via .dumbledoer/tmp/memory.md.tmp + atomic rename:
   remove archived Change Log / Checkpoint Registry rows and Task Details
   subsections; add the Archive Index row; reduce the Session Log row to
   summary form; set archived tasks' Checkpoint column to `archived`
```

A failure before step 4's rename leaves `memory.md` untouched. A pre-existing
identical archive file makes a re-run idempotent: overwrite only if
content-identical, otherwise write `{sessionId}-2.md` and flag in Notes.

## memory.md after archiving

- `## Archive Index` row added: `| Session ID | Archived At | Archive File | Tasks Archived | Outcome |`
- Session Log row kept with End Time intact and Outcome suffixed ` (archived)`
- Task Registry rows for archived tasks kept, Checkpoint column = `archived`

---

## Retrieval

| Caller | Behavior when the referenced Task/Session is in the Archive Index |
|---|---|
| `report` | Read the archive record(s); include archived tasks in the analysis, marked `(archived)` |
| `rollback T-NNN` | Read the archive record; restore the task's Details subsection into memory.md; reset status to `pending`; remove the subsection from the archive record and update its Archive Index `Tasks Archived` cell; then run the normal rollback flow |
| `status --verbose` | Show a one-line summary per archived task with a pointer to the archive file (never inline full details) |

**Missing archive file**: halt the operation with exactly:

```
Error: archive record {path} listed in Archive Index but not found.
The file may have been deleted. Restore it from version control or remove
the Archive Index row to acknowledge the loss. No changes were made.
```

