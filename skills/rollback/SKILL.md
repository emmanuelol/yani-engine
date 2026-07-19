---
name: dumbledoer-rollback
description: Roll back dumbledoer task changes to restore files to their pre-task state. Supports per-task, full, or session-boundary rollback.
---

Base directory for this skill: (project root where dumbledoer is installed)

# /dumbledoer:rollback — Roll Back Changes

**References** (read before Section 1): `dumbledoer/lib/common-preamble.md`, `dumbledoer/lib/checkpoint-protocol.md`

**Lazy references**: `dumbledoer/lib/memory-schema.md` (load only if the repair flow triggers), `dumbledoer/lib/archive-protocol.md` (load at archived-task retrieval), `dumbledoer/lib/knowledge-protocol.md` (load at Section 3a step 7 — knowledge capture)

## Usage

```
/dumbledoer:rollback T-NNN              # Roll back a specific completed task
/dumbledoer:rollback --all              # Roll back all completed tasks (reverse order)
/dumbledoer:rollback --to S-YYYYMMDD-HHmmss  # Roll back to session boundary
```

---

## Section 1 — Parse and Validate Input

1. Parse the rollback form from arguments.
2. Verify `memory.md` exists; if not: `Error: memory.md not found.` and stop.
3. Read and validate `memory.md` (validation checklist, `lib/common-preamble.md`; on failure load `lib/memory-schema.md` for the repair flow).
4. **Archived-task check**: if the task's Checkpoint column is `archived` (task listed
   in an Archive Index row), load `lib/archive-protocol.md` (lazy reference) and run
   its rollback retrieval flow first: restore the Task Details subsection from the
   archive record into memory.md, remove it from the record, and update the Archive
   Index `Tasks Archived` cell. Then continue below. If the archive file is missing:
   output the missing-archive error from `lib/archive-protocol.md` and stop.
5. Verify preconditions:
   - **T-NNN form**: task exists in Task Registry AND status=`completed`. Rollback dir `.dumbledoer/rollbacks/T-NNN/` exists.
   - **--all form**: at least one `completed` task exists.
   - **--to S-XXX form**: S-XXX exists in Session Log.

Errors:
- Task not found: `Error: task T-NNN not found in Task Registry.`
- Task not completed: `Error: T-NNN has status '{status}' — only completed tasks can be rolled back. Use /dumbledoer:status to inspect.`
- Rollback files missing: `Error: rollback files for T-NNN not found in .dumbledoer/rollbacks/. Manual recovery required — see memory.md Change Log for the original content.`
- Session not found: `Error: session S-XXX not found in Session Log.`

---

## Section 2 — Rollback Preview

This command's conversational output is category `simple`
(`lib/compression-policy.md`): caveman `full` when compression is enabled. The
preview block, confirmation prompts, and all exact error/summary strings are
preserved verbatim at every level.

Before applying any change, display a preview:

```
Rollback preview for T-NNN ({title}):
  Files to restore:
    - {relative/path/file1} (last modified: {timestamp})
    - {relative/path/file2} (last modified: {timestamp})

Proceed? (yes/no)
```

If user says no or cancel: exit with no changes.

---

## Section 3a — Per-Task Rollback (T-NNN form)

1. Read all files in `.dumbledoer/rollbacks/{taskId}/`.
2. Decode filename: replace `__` → `/` and `__colon__` → `:` to get original path.
3. For each file in reverse modification order (newest first):
   a. Write current file to `.dumbledoer/tmp/{filename}.tmp` as safety copy.
   b. Copy rollback file to target path via atomic rename.
   c. Append to Change Log: `| {now} | {taskId} | {path} | Rolled back to pre-task state | rolled-back | User-requested rollback |`
4. Update memory.md task entry:
   - Status: `pending`
   - Owner: `—`
   - Checkpoint: `none`
   - CodeGraph Impact: `—`
   - Notes: append `Rolled back {ISO timestamp}`
5. Update Task Registry row to match.
6. Run `codegraph sync`.
7. **Capture the failure** (OP-5, `lib/knowledge-protocol.md` — load now if not loaded):
   - If a success entry exists for {taskId}: rewrite that SAME note in place — flip
     `type` to `failure`, keep the id and filename, append the
     `> [!warning] Rolled back` callout with reason and timestamp.
   - Otherwise: create a new `failure` entry (attempted approach, why it was rolled
     back, `## Retry Conditions`).
   - Update `index.md` (regroup if the type changed) and append a reversal line to
     the current session's `timeline.md` section, in the same operation.
   - Registry absent or entry malformed: apply the protocol's tolerance rules
     (warn, never abort the rollback).
8. Output: `Rolled back 1 task(s), restored N file(s).`

---

## Section 3b — Full Rollback (--all form)

1. Read Task Registry. Collect all tasks with status=`completed`.
2. Sort by Task ID descending (T-NNN highest first = reverse registration order).
3. For each task: apply Section 3a (per-task rollback). Confirm each before applying if > 3 tasks.
4. Run `codegraph sync` once at end (not after each task).
5. Output: `Rolled back N task(s), restored M file(s).`

---

## Section 3c — Session-Boundary Rollback (--to S-XXX form)

1. Find S-XXX in Session Log. Read its `endTime`.
2. Find all tasks in Task Details whose completion timestamp (from Change Log) is AFTER S-XXX `endTime`.
3. Sort by Task ID descending.
4. Apply Section 3a for each task.
5. Run `codegraph sync` once at end.
6. Output: `Rolled back N task(s) (completed after session S-XXX), restored M file(s).`

