# checkpoint-protocol: Mandatory Checkpoint and Atomic Write Protocol

Every `change` task MUST follow this protocol exactly, in the order specified.
No exceptions. A session that skips any step violates the protocol and risks data loss.

---

## 6-Step Protocol (mandatory order)

### Step 1 — Write Rollback Copy

Before any other action, copy the original file to the rollback directory.

```
Source:      {relative/path/to/file}
Destination: .dumbledoer/rollbacks/{taskId}/{encodedPath}
```

**Encoding rule**: Replace `/` with `__` and `:` with `__colon__` in the filename.
Example: `prompts/system.md` → `.dumbledoer/rollbacks/T-001/prompts__system.md`

**CRITICAL**: If `.dumbledoer/rollbacks/{taskId}/` already contains this file,
DO NOT overwrite it. The first copy is the true pre-dumbledoer original.

**On failure**: Halt task execution. Do not proceed to Step 2. Log error in Notes
field of task detail.

---

### Step 2 — Write Intent to Change Log

Append a `planned` entry to the Change Log in `memory.md` BEFORE applying the change.

```
| {ISO timestamp} | {taskId} | {relative/path} | {one-line summary} | planned | {rationale} |
```

This ensures that if the session dies mid-write, the next session can detect the
planned-but-not-applied state and resolve it.

---

### Step 3 — Write Checkpoint File

Write the checkpoint JSON to `.dumbledoer/checkpoints/{checkpointId}.json`.

**Checkpoint JSON schema**:
```json
{
  "checkpointId": "{taskId}-step{N}-{sessionId}",
  "taskId": "T-NNN",
  "stepIndex": 1,
  "sessionId": "S-YYYYMMDD-HHmmss",
  "description": "Human-readable: about to do X to Y",
  "timestamp": "ISO 8601",
  "files": {
    "relative/path/to/file": "<full original content as string>"
  },
  "codeGraphSnapshot": {
    "symbol": "functionOrFileQueried",
    "impactRadius": 3,
    "affectedSymbols": ["sym1", "sym2"],
    "affectedFiles": ["file1.md", "file2.md"],
    "rawOutput": "full codegraph_impact output"
  },
  "nextStepDescription": "Precise description of what to do next if resuming from here"
}
```

After writing, add an entry to the Checkpoint Registry in `memory.md`:
```
| {checkpointId} | {taskId} | {stepIndex} | {sessionId} | {comma-separated files} |
```

Also update the task's `Checkpoint` field in both Task Registry and Task Details.

---

### Step 4 — Write New Content to Temp File

Write the complete new file content to `.dumbledoer/tmp/{filename}.tmp`.

Do NOT write directly to the target path yet.

**On write failure**: Halt. The original file is intact (Step 1 copied it). The
checkpoint exists (Step 3). The next session can detect the `.tmp` file as an
incomplete operation and offer to apply or discard it.

---

### Step 5 — Atomic Rename to Target Path

Rename `.dumbledoer/tmp/{filename}.tmp` to the target path.

This is the only step that modifies the target file. If the session dies between
Step 4 and Step 5, the original file is intact and the `.tmp` file is detectable.

---

### Step 6 — Update Change Log to Applied

Update the `planned` entry from Step 2 to `applied`:
```
| {ISO timestamp} | {taskId} | {relative/path} | {one-line summary} | applied | {rationale} |
```

Also update the task's `CodeGraph Impact` field in Task Details (if not already set).

---

## Failure Handling (per step)

If any protocol step fails mid-task, clean up per this table, report what was cleaned
and where the recovery point is, then halt the task. The prior checkpoint (or the
Step-1 rollback copy) is ALWAYS the authoritative recovery point. Never silently
swallow a failure.

| Failed step | Artifacts that may exist | Cleanup action | Recovery point |
|---|---|---|---|
| 1 — rollback copy | none / partial copy | Delete the partial copy; halt; log in task Notes | Target file (untouched) |
| 2 — planned log entry | rollback copy | Keep the rollback copy (harmless); halt; log | Target file (untouched) |
| 3 — checkpoint JSON / registry row | rollback copy, planned entry, maybe JSON | Delete the unregistered JSON; mark planned entry `rolled-back`; halt | Target file (untouched) |
| 4 — tmp write | all of the above, partial `.tmp` | Delete the `.tmp`; mark planned entry `rolled-back`; halt | Prior checkpoint / rollback copy |
| 5 — atomic rename | complete `.tmp` | Leave the `.tmp` for the session-start scan (class O1 below); halt | Prior checkpoint / rollback copy |
| 6 — applied log update | change applied, entry still `planned` | Resolved by class O4 on the next scan | Applied state (the change is live) |

**Invariant**: cleanup actions never overwrite the Step-1 rollback copy — it is the
pre-dumbledoer original.

---

## Orphan Recovery Scan (every session start and on resume)

Scan `.dumbledoer/tmp/`, `.dumbledoer/checkpoints/`, `.dumbledoer/rollbacks/`,
and the Change Log for the five orphan classes and resolve them. Only class O1 prompts
the user — all others auto-resolve with a report line.

| Class | Detection | Resolution | Prompt? |
|---|---|---|---|
| O1 | `.tmp` file + matching checkpoint in Checkpoint Registry | Offer: (a) apply the planned change or (b) discard the `.tmp`. Either choice leaves zero artifacts | Yes |
| O2 | `.tmp` file with no matching checkpoint | Auto-discard; report | No |
| O3 | Checkpoint JSON file not listed in Checkpoint Registry | If a `planned` Change Log entry matches it: add the registry row; otherwise auto-discard the JSON; report | No |
| O4 | Change Log entry stuck at `planned` (no `applied`/`rolled-back`) | If the target file is byte-identical to the rollback copy: mark `rolled-back`. If it differs and a complete `.tmp` exists: escalate to O1. If it differs with no `.tmp`: mark `applied` (the change is live); report | Only via O1 escalation |
| O5 | Rollback copy in `rollbacks/{taskId}/` with NO Change Log entry (any status) for that task + file | Possibly-partial copy from a kill during Step 1 — the target was never modified. Auto-discard the copy; report. NEVER restore from it | No |

**Post-scan invariant**: zero unclassified artifacts remain. Output exactly one of:

```
Recovery scan: clean
```
```
Recovery scan: {N} artifact(s) resolved
  - {class}: {artifact} → {action taken}
```

---

## Checkpoint Restore Protocol (for /dumbledoer resume)

To restore state from checkpoint `{checkpointId}`:

1. Read `.dumbledoer/checkpoints/{checkpointId}.json`.
2. For each file in `checkpoint.files`:
   a. Write current file to `.dumbledoer/tmp/{filename}.tmp` as a safety copy.
   b. Write `checkpoint.files[path]` (the pre-change original) to target via rename.
3. Update task status to `in_progress` with current session ID.
4. Continue execution from `checkpoint.stepIndex + 1`.

---

## Multi-Step Tasks

For tasks with multiple file modifications, each modification gets its own checkpoint
(step index increments). The task owns all checkpoints from step 1 to completion.

Example: T-003 modifies 3 files → creates checkpoints T-003-step1-S-..., T-003-step2-S-..., T-003-step3-S-...

The task's Checkpoint field always points to the LATEST checkpoint.

