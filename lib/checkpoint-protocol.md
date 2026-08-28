# checkpoint-protocol: Mandatory Checkpoint and Atomic Write Protocol

Every `change` task MUST follow this protocol exactly, in the order specified.
No exceptions. A session that skips any step violates the protocol and risks data loss.

---

## 6-Step Protocol (Automated)

**🚨 CRITICAL OVERRIDE:** You, the LLM agent, MUST NOT execute these steps manually. You MUST NOT create files in `.yani/rollbacks/`, `.yani/checkpoints/`, or `.yani/tmp/`. 

To apply a code change, you MUST call the `write_file_with_review` tool. Pass the target path (e.g., `app/main.py`) and the full new content. The Python tool handles the following 6 steps AUTOMATICALLY:
1. Writes Rollback Copy
2. Writes Intent to Change Log
3. Writes Checkpoint JSON and registers it
4. Writes New Content to Temp File
5. Atomic Rename (on Diff-Gate approval)
6. Updates Change Log to Applied

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
pre-yani-engine original.

---

## Orphan Recovery Scan (every session start and on resume)

Scan `.yani/tmp/`, `.yani/checkpoints/`, `.yani/rollbacks/`,
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

## Checkpoint Restore Protocol (for /yani-engine resume)

To restore state from checkpoint `{checkpointId}`:

1. Read `.yani/checkpoints/{checkpointId}.json`.
2. For each file in `checkpoint.files`:
   a. Write current file to `.yani/tmp/{filename}.tmp` as a safety copy.
   b. Write `checkpoint.files[path]` (the pre-change original) to target via rename.
3. Update task status to `in_progress` with current session ID.
4. Continue execution from `checkpoint.stepIndex + 1`.

---

## Multi-Step Tasks

For tasks with multiple file modifications, each modification gets its own checkpoint
(step index increments). The task owns all checkpoints from step 1 to completion.

Example: T-003 modifies 3 files → creates checkpoints T-003-step1-S-..., T-003-step2-S-..., T-003-step3-S-...

The task's Checkpoint field always points to the LATEST checkpoint.

