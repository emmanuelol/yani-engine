# memory-schema: memory.md Field Definitions and Validation Rules

This file is the authoritative reference for `memory.md` structure. All commands
MUST read this file before reading or writing `memory.md`.

---

## Required Sections (all must be present)

1. `## Config` — key-value pairs: `budget_limit`, `budget_threshold_pct`, `session_count`, `created`
2. `## Project Goal` — one paragraph
3. `## Scope` — bullet list of in-scope components
4. `## Budget & Quota Tracking` — Markdown table
5. `## Task Registry` — Markdown table
6. `## Task Details` — subsections, one per task
7. `## Change Log` — Markdown table
8. `## Session Log` — Markdown table
9. `## Checkpoint Registry` — Markdown table
10. `## Open Questions` — bullet list or empty
11. `## Edge Case Coverage` — Markdown table (created by `/dumbledoer:start` edge case Q&A; optional on first session start, required after any edge case Q&A completes)
12. `## Archive Index` — Markdown table (optional until the first archive run completes; required after — see `lib/archive-protocol.md`)

---

## Field Definitions

### Config Fields

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `budget_limit` | integer | Estimated total token budget for this project | 5000000 |
| `budget_threshold_pct` | integer (1–99) | Trigger graceful shutdown at this % of budget_limit | 80 |
| `session_count` | integer | Total sessions run; increment on each session start | 0 |
| `created` | YYYY-MM-DD | Date memory.md was first created | (set at init) |
| `docs_path` | string | Relative path to the documentation directory supplied via `--docs` at start; reused by `/dumbledoer:update-docs` when `--docs` is not passed explicitly | (set by `/dumbledoer:start`) |
| `last_docs_update` | ISO 8601 \| null | Timestamp of the most recent successful `/dumbledoer:update-docs` run; null until the first run completes; used by delta analysis to scope git log queries | null |
| `last_docs_update_session` | Session ID \| null | Session ID of the session that last ran `/dumbledoer:update-docs` successfully; null until first run | null |
| `archive_keep_sessions` | integer ≥ 1 (optional) | How many most-recent terminal sessions stay in memory.md in full detail; older terminal sessions are archived (`lib/archive-protocol.md`) | 1 |
| `knowledge_path` | string | Relative path to the cross-session knowledge registry directory; created by `/dumbledoer:start` on first run; all registry operations resolve against it (`lib/knowledge-protocol.md`) | `knowledge/` |
| `last_knowledge_docs_sync` | ISO 8601 \| `never` | Timestamp of the last successful registry-informed `/dumbledoer:update-docs` run; `never` until the first run completes; OP-9 docs-sync reads only entries newer than this value and updates it on success only | `never` |

### Task Registry Columns

| Column | Values | Description |
|--------|--------|-------------|
| Task ID | `T-NNN` (3-digit, zero-padded; extend to 4 if >999) | Unique task identifier |
| Title | string | One-line task description |
| Type | `analysis` \| `change` \| `validation` \| `report` | Task category |
| Status | see Status Enum | Current execution state |
| Owner | Session ID or `—` | Session currently claiming this task |
| Depends On | comma-separated Task IDs or `none` | Prerequisites |
| Session | Session ID or `—` | Session that registered this task |
| Checkpoint | Checkpoint ID or `none` | Last saved resume point |

### Task Status Enum

| Value | Meaning |
|-------|---------|
| `pending` | Not yet started |
| `in_progress` | Actively being worked on (locked by a session or sub-agent) |
| `interrupted` | Was in_progress when budget/quota was exhausted; safe to resume |
| `blocked` | Waiting on another task or external input |
| `completed` | Done and verified against success criteria |
| `deferred` | Intentionally postponed |

### Task Detail Fields (per task subsection)

| Field | Required | Description |
|-------|----------|-------------|
| Type | Yes | Same as Task Registry Type |
| Status | Yes | Same as Task Registry Status |
| Owner | Yes | Session ID or `—` |
| Depends On | Yes | Task IDs or `none` |
| Assigned Session | Yes | Session ID or `—` |
| Description | Yes | What and why |
| Inputs | Yes | File paths or data sources read |
| Outputs | Yes | File paths modified or created |
| Success Criteria | Yes | How to verify completion |
| Estimated Effort | Yes | `small` \| `medium` \| `large` |
| Parallelizable | Yes | `yes` \| `no` |
| CodeGraph Impact | Yes | `codegraph_impact` result summary (populated before first file write); `—` until then |
| Checkpoint | Yes | Last checkpoint ID or `none` |
| Resume Instructions | Yes | Step-by-step instructions for a new session to continue |
| Notes | Yes | Context, blockers, decisions; `—` if none |

### Change Log Columns

| Column | Description |
|--------|-------------|
| Timestamp | ISO 8601 |
| Task ID | `T-NNN` |
| File | Relative path |
| Change Summary | One-line description |
| Status | `planned` \| `applied` \| `rolled-back` |
| Rationale | Why this change was made |

### Session Log Columns

| Column | Description |
|--------|-------------|
| Session ID | `S-{YYYYMMDD-HHmmss}` |
| Start Time | ISO 8601 |
| End Time | ISO 8601 or `—` if active |
| Tasks Claimed | Comma-separated Task IDs |
| Outcome | `completed` \| `interrupted-budget` \| `interrupted-quota` \| `interrupted-user` \| `error` \| `active` \| `iterate` \| `iterate-interrupted` |

### Checkpoint Registry Columns

| Column | Description |
|--------|-------------|
| Checkpoint ID | `{taskId}-step{N}-{sessionId}` |
| Task ID | `T-NNN` |
| Step | Step index (1-based) |
| Session ID | Session that created the checkpoint |
| Files Snapshotted | Comma-separated relative paths |

---

## Status Transition Rules

```
pending     → in_progress   (session claims task)
in_progress → completed     (verified against success criteria)
in_progress → interrupted   (budget/quota exhaustion or session end before completion)
interrupted → in_progress   (resumed from checkpoint)
interrupted → pending       (rolled back)
pending     → blocked       (dependency incomplete)
blocked     → pending       (dependency completed)
pending     → deferred      (user decision)
```

**Prohibited transitions**:
- `completed` → any other status (completed is terminal unless rolled back, which resets to `pending`)
- `in_progress` with no `owner` (owner must be set when transitioning to `in_progress`)

---

## Validation Rules (checked on every session start)

**Rule 1**: Every row in Task Registry MUST have a corresponding `### T-NNN:` subsection
in Task Details — except tasks listed in an Archive Index `Tasks Archived` column,
whose details live in the referenced archive record.

**Rule 2**: No task may have status `in_progress` without a non-empty `owner` value.

**Rule 3**: Every `owner` value MUST match a Session ID in the Session Log.

**Rule 4**: Every non-`none` checkpoint value in Task Registry MUST match a row in
Checkpoint Registry — or be the literal `archived` for a task listed in the Archive
Index (its checkpoint rows live in the archive record).

**Rule 5**: `budget_threshold_pct` MUST be an integer between 1 and 99 (inclusive).

**On violation of any rule**: Apply FR-016 — halt, diagnose the specific rule that
failed, display the offending field values, offer:
  (a) Reset to last valid checkpoint (most recent Checkpoint Registry entry)
  (b) Archive the corrupted file as `memory.md.corrupted.{timestamp}` and start fresh

---

## Registration-Time Validation Rules (Rules 7–9)

Applied whenever any command registers new tasks (plan registration in start,
refinement in iterate) — NOT on session start, so existing files are never
retroactively failed. Rejection is **atomic**: on any failure, no task from the
proposed plan is written, and the command re-enters plan refinement in the same
session rather than aborting.

**Rule 7 — Task ID uniqueness**: No Task ID may appear more than once across the
proposed plan, the existing Task Registry, and the Archive Index `Tasks Archived`
columns. On violation, output exactly:

```
Error: task plan rejected — duplicate task ID {T-NNN}.
{T-NNN} appears {count} times (in: {locations}). Task IDs must be unique.
No tasks were registered.
```

**Rule 8 — Referential completeness**: Every ID in every `Depends On` field must
resolve to a task in the proposed plan, the Task Registry, or the Archive Index.
On violation, output exactly:

```
Error: task plan rejected — {T-AAA} depends on {T-XXX}, which does not exist.
Add the missing task or correct the dependency. No tasks were registered.
```

**Rule 9 — Acyclicity** (elimination method; scales to 1000+ tasks):
1. Mark dependencies on already-completed or archived tasks as satisfied.
2. Repeatedly remove from the proposed plan any task whose dependencies are all
   satisfied or removed.
3. If tasks remain, they form one or more cycles. Walk `Depends On` links among
   the remaining tasks, starting from the lowest remaining Task ID, and output
   exactly:

```
Error: task plan rejected — circular dependency detected:
{T-AAA} → {T-BBB} → … → {T-AAA}
Break the cycle by removing or reordering one dependency. No tasks were registered.
```

When all three rules pass, registration proceeds silently (no validation chatter).

---

## ID Generation Rules

### Session IDs
Format: `S-{YYYYMMDD-HHmmss}` (e.g., `S-20260521-093045`)
Uniqueness: timestamp to the second. If collision, append `-2`, `-3`, etc.

### Task IDs
Format: `T-{NNN}` zero-padded 3-digit (e.g., `T-001`). Extend to 4 digits if >999.
Generation: scan Task Registry for highest existing ID, increment by 1.

### Edge Case IDs
Format: `EC-{NNN}` zero-padded 3-digit (e.g., `EC-001`).
Generation: scan `## Edge Case Coverage` table for highest existing ID, increment by 1.

---

## Edge Case Coverage Section

### Edge Case Coverage Columns

| Column | Description |
|--------|-------------|
| Edge Case ID | `EC-NNN` (3-digit zero-padded; extend to 4 if >999) |
| Component | The in-scope component area this edge case belongs to |
| Description | Brief description of the edge case or boundary condition identified |
| Disposition | `addressed` \| `dismissed` \| `already-covered` |
| Task IDs | Comma-separated T-NNN IDs if disposition is `addressed`; `—` otherwise |
| User Reason | User's stated reason if disposition is `dismissed`; reference text if `already-covered`; `—` if `addressed` |

### Disposition Rules

| Disposition | Meaning | Required Fields |
|-------------|---------|----------------|
| `addressed` | User chose to handle this edge case; tasks generated in plan | Task IDs must be non-empty after plan generation |
| `dismissed` | User explicitly declared out of scope | User Reason required; also written to `## Open Questions` |
| `already-covered` | User indicated an existing goal or task covers it | User Reason contains the reference (goal text or T-NNN) |

### Validation Rule 6 (added)

Every row with disposition `addressed` MUST have at least one valid Task ID in the Task IDs column after plan generation completes. Rows written during Q&A before plan generation may have `TBD` as a placeholder; `TBD` is invalid after plan generation.

---

### Checkpoint IDs
Format: `{taskId}-step{N}-{sessionId}` (e.g., `T-001-step2-S-20260521-093045`)

---

## Archive Index Section

### Archive Index Columns

| Column | Description |
|--------|-------------|
| Session ID | `S-…` of the archived session |
| Archived At | ISO 8601 timestamp of the archive run |
| Archive File | Relative path, `.dumbledoer/archive/{sessionId}.md` |
| Tasks Archived | Comma-separated `T-NNN` whose Task Details moved to the record; `—` if none |
| Outcome | The session's original outcome enum value |

Maintained exclusively by the archive protocol (`lib/archive-protocol.md`). Rows are
appended at archive time and edited only when a rollback restores an archived task.
