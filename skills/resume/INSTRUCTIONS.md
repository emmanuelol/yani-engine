---
name: resume
description: Resume an interrupted yani-engine session from the last checkpoint. Use when a previous session was stopped by budget exhaustion, user interruption, or Gemini Code restart.
---

Base directory for this skill: (project root where yani-engine is installed)

# /yani-engine:resume — Resume an Interrupted Session

**References** (read before Section 1): `yani-engine/lib/common-preamble.md`, `yani-engine/lib/memory-schema.md`, `yani-engine/lib/checkpoint-protocol.md`, `yani-engine/lib/budget-detection.md`, `yani-engine/lib/compression-policy.md`

**Lazy references**:
- `yani-engine/lib/knowledge-protocol.md` (load at Section 2c — knowledge registry)
- `yani-engine/lib/archive-protocol.md` (load at Section 8 — session close)

(Task execution in Section 7 delegates to `skills/start/SKILL.md` Section 8, which loads its own references.)

## Parameters

```
/yani-engine:resume
  --budget-threshold <pct>   Optional. Override default shutdown threshold for this session.
```

---

## Section 1 — Verify memory.md Exists

1. Check for `memory.md` at project root.
2. If absent: output exactly `Error: memory.md not found. Run /yani-engine:start to begin a new session.` and stop.

---

## Section 2 — Validate memory.md

1. Read `memory.md` in full.
2. Run the validation checklist from `lib/common-preamble.md`.
3. If ANY rule fails:
   - Output: `memory.md validation failed: Rule N — <specific description of failure>.`
   - Offer: `(a) Reset to last valid checkpoint in Checkpoint Registry. (b) Archive memory.md as memory.md.corrupted.{timestamp} and start fresh.`
   - Wait for user choice. Execute chosen option. Stop — let user re-invoke after repair.
4. If all rules pass: restore the session's compression state
   (`lib/compression-policy.md` — the caveman ruleset is bundled at
   `skills/caveman/SKILL.md`): read `compression_enabled` from Config and adopt
   it from the first response onward WITHOUT re-prompting or re-showing the
   session-start notice. Absent field ⇒ `true` (write the field on the next
   Config update). Invalid value ⇒ non-fatal: report it and ask the user to pick
   `true` or `false`. Then proceed to Section 2b.

---

## Section 2b — Orphan Recovery Scan

Run the Orphan Recovery Scan from `lib/checkpoint-protocol.md` BEFORE stale-lock
handling:

1. Scan `.yani/tmp/`, `.yani/checkpoints/`, `.yani/rollbacks/`,
   and the Change Log for orphan classes O1–O5.
2. Auto-resolve O2, O3, O4, and O5 per the protocol table. Prompt the user only for O1
   (complete `.tmp` with a registered checkpoint — apply or discard).
3. Emit the scan report in the protocol's exact format (`Recovery scan: clean` or the
   per-artifact resolution list).
4. After the scan, zero unclassified artifacts may remain. Never overwrite a Step-1
   rollback copy while resolving.

---

## Section 2c — Load Knowledge Registry

**Load `yani-engine/lib/knowledge-protocol.md` now** (lazy reference).

1. Resolve `{knowledge_path}` from memory.md Config (default `knowledge/`).
2. If the registry exists: run OP-2 selective-load and output the load-summary line.
   Apply the protocol's tolerance rules (malformed entries skipped with a warning,
   never fatal).
3. If the registry is absent: print a one-line note that it is missing and that
   `/yani-engine:start` creates it; continue without knowledge context (resume
   never initializes the registry — protocol invariant 3).
4. Carry the loaded knowledge into Sections 5–7.

---

## Section 3 — Detect Stale Locks (FR-011)

Scan Task Registry for tasks with status `in_progress` where Owner ≠ current session ID.

For each stale lock found:
- Treat as `interrupted` (do NOT execute or modify yet).
- Add to the interrupted-tasks list for Section 4.

---

## Section 4 — Detect Explicitly Interrupted Tasks

Scan Task Registry for tasks with status `interrupted`.
Add to the interrupted-tasks list.

---

## Section 5 — Present Interrupted Tasks (if any)

If the interrupted-tasks list is non-empty:

For each interrupted task, display:
```
Interrupted task: {taskId} — {title}
  Status: {interrupted/stale-lock}
  Last checkpoint: {checkpointId or 'none'}
  Last step: {stepIndex or 'unknown'}
  Next action: {resumeInstructions first line}
  Options: (a) Resume from checkpoint  (b) Roll back to pre-task state  (c) Skip (defer)
```

**Consult the knowledge registry** (OP-3, `lib/knowledge-protocol.md`) before
presenting options: when a loaded `failure` entry or its Retry Conditions overlap
the interrupted task's approach, recommend the better option and cite the entry,
e.g. `Registry note: [[K-NNN-slug]] recorded this approach failing — rollback (b) recommended.`

Wait for user to select an option for EACH interrupted task before doing any work.

Apply each selection:

### (a) Resume
1. Load checkpoint from `lib/checkpoint-protocol.md` restore protocol.
2. If checkpoint file missing: output warning and offer rollback-only option.
3. Restore file state from checkpoint.files via write-to-tmp-then-rename.
4. Update task status to `in_progress` with current session ID in memory.md.
5. Continue execution from stepIndex + 1.

### (b) Rollback
1. Read files from `.yani/rollbacks/{taskId}/`.
2. For each file: write current to `.yani/tmp/` (safety), then rename rollback → target.
3. Update Change Log: append rolled-back entries.
4. Set task status to `pending`, clear Owner and Checkpoint in memory.md.
5. Run `codegraph sync` to refresh index.

### (c) Skip
1. Set task status to `deferred` in memory.md.
2. Clear Owner.
3. No file changes.

---

## Section 6 — Session Menu (Pending Tasks)

After resolving all interrupted tasks, display pending tasks:

```
Pending tasks available:
  T-NNN: {title} [{type}] [{effort}] {depends-on-note}
  ...

Which tasks would you like to execute this session? (Enter task IDs, 'all', or 'none')
```

Wait for user confirmation. Proceed only with confirmed tasks.

---

## Section 7 — Claim and Execute

1. Generate a new session ID (format and collision rules: `lib/common-preamble.md`).
2. Append Session Log entry: start time, tasks claimed, outcome=`active`.
3. Increment `session_count` in Config.
4. For each confirmed task: execute following Section 8 of `yani-engine/skills/start/SKILL.md`
   (same execution loop — sub-agent spawning, checkpoint protocol, CodeGraph rules).
5. Apply budget detection throughout using `lib/budget-detection.md`.
6. On budget threshold: apply Section 9 of `yani-engine/skills/start/SKILL.md` (graceful shutdown).

---

## Section 8 — Normal Session Close

Same as Section 10 of `yani-engine/skills/start/SKILL.md` — including the archive
check (load `yani-engine/lib/archive-protocol.md` lazily and run the trigger).

