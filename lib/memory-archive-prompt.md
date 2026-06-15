# memory-archive-prompt: Session Memory Archive Prompt

Prompts the user at normal session close to archive the full `memory.md` file and
reinitialize it for the next session. Loaded lazily at Section 10 of
`skills/start/SKILL.md` (and, by delegation, at Section 8 of
`skills/resume/SKILL.md`).

---

## Trigger Conditions

Run this protocol **after** the automatic archive check (Section 10 step 6) and
**before** the final session summary output.

**Show the prompt when ALL of the following are true**:
- Session is ending via the **normal close** path (Section 10 / Section 8)
- `memory.md` exists at the project root
- `memory.md` contains at least one data row in the `## Session Log` table

**Do NOT show the prompt when ANY of the following is true**:
- Session ends via **graceful shutdown** (budget exhaustion, Section 9)
- `memory.md` is absent
- `memory.md` has no Session Log data rows (header-only or section absent)
- The session was a `--dry-run`

If the trigger condition is not met, do nothing. Proceed silently to the final
session summary.

---

## Prompt Output

When the trigger condition is met, output exactly the following text (substituting
`{sessionId}` with the current session ID, `{N}` with completed task count, and
`{M}` with remaining task count):

```
Session {sessionId} archived and ready for review.
Tasks completed: {N} | Tasks remaining: {M}

Would you like to archive memory.md to start fresh for the next session?
  [archive]  Save a full snapshot of memory.md → .dumbledoer/archive/ and reset to a blank state.
  [skip]     Keep memory.md as-is and close normally.
```

The two option lines MUST be indented with exactly two spaces. No additional text
or formatting between the session summary line and the prompt question.

---

## User Response Handling

| User says (case-insensitive) | Action |
|---|---|
| `archive` | Run the Full-Reset Archive Protocol (see below) |
| `skip` | Output exactly: `memory.md kept. Session closed.` and stop |
| Any other input | Output exactly: `Please reply 'archive' or 'skip'.` then re-display the two-option `[archive]` / `[skip]` block; wait for another reply (loop until valid) |

---

## Full-Reset Archive Protocol

Triggered when the user replies `archive`. Execute steps in this exact order.
A failure before step 4's rename MUST leave `memory.md` untouched.

### Step 1 — Write temporary archive

Write the verbatim contents of `memory.md` to:
```
.dumbledoer/tmp/memory-archive-{sessionId}.tmp
```

### Step 2 — Verify temporary archive

The `.tmp` file MUST satisfy ALL of:
- Non-empty
- Contains `## Config` as a section header
- Parseable as Markdown

On verification failure: output exactly
`Archive verification failed. memory.md was not modified. Session closed.`
and stop — do not proceed to step 3.

### Step 3 — Rename to archive record

Atomic rename (or copy + delete on platforms without atomic rename):
```
.dumbledoer/tmp/memory-archive-{sessionId}.tmp
  → .dumbledoer/archive/memory-{sessionId}-{ISO8601}.md
```

`{ISO8601}` is the current date-time in the format `YYYY-MM-DDTHH-MM-SS`
(colons replaced with hyphens for filesystem compatibility).

On failure: output exactly
`Error: could not write archive record. memory.md was not modified. Session closed.`
and stop.

### Step 4 — Reinitialize memory.md

4a. Locate `dumbledoer/templates/memory-template.md`. If not found: output exactly
`Error: memory template not found at dumbledoer/templates/memory-template.md. memory.md was not modified. Archive record saved at {path}.`
(substitute `{path}` with the archive record path from step 3) and stop.

4b. Write the template contents to `.dumbledoer/tmp/memory.md.tmp`, substituting:
- `{{DATE}}` → today's date in `YYYY-MM-DD` format
- `{{COMPRESSION_ENABLED}}` → the session's resolved compression state (`true` or `false`)
- `{{PROJECT_GOAL}}` → leave as placeholder `{{PROJECT_GOAL}}`
- `{{SCOPE_ITEMS}}` → leave as placeholder `{{SCOPE_ITEMS}}`

4c. Atomic rename `.dumbledoer/tmp/memory.md.tmp` → `memory.md`.

On rename failure: output exactly
`Error: archive saved but memory.md reset failed. Restore from archive at {path} if needed. Session closed.`
(substitute `{path}` with the archive record path from step 3) and stop.

### Step 5 — Confirm to user

Output exactly:
```
memory.md archived → .dumbledoer/archive/memory-{sessionId}-{ISO8601}.md
memory.md reset to blank state. Next /dumbledoer:start will begin fresh.
Session closed.
```

---

## Error Messages (exact strings)

| Condition | Required output |
|---|---|
| Step 2 verification fails | `Archive verification failed. memory.md was not modified. Session closed.` |
| Step 3 rename fails | `Error: could not write archive record. memory.md was not modified. Session closed.` |
| Step 4 template not found | `Error: memory template not found at dumbledoer/templates/memory-template.md. memory.md was not modified. Archive record saved at {path}.` |
| Step 4 rename fails | `Error: archive saved but memory.md reset failed. Restore from archive at {path} if needed. Session closed.` |

---

## Post-Condition Assertions

After a successful archive (step 5 reached):
- `.dumbledoer/archive/memory-{sessionId}-{ISO8601}.md` EXISTS and is non-empty
- `memory.md` EXISTS and contains `## Config` and `## Task Registry` sections
- `memory.md` does NOT contain Session Log rows from the archived session
- `.dumbledoer/tmp/memory-archive-{sessionId}.tmp` does NOT exist

After a skip:
- `memory.md` is byte-identical to its state before the prompt was shown
- No files created under `.dumbledoer/archive/` or `.dumbledoer/tmp/` by this operation

