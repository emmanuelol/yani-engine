> [!IMPORTANT] EXECUTION DIRECTIVE: When the user invokes this command, you MUST immediately execute the corresponding JSON tool defined in the commands/ directory. Do not explain the command to the user. Do not ask the user to run it in their terminal. Execute the tool call silently and report the output.
> FALLBACK PROTOCOL: If the JSON tool call fails or cannot be resolved, you MUST use the Bash tool to execute the command directly via ~/.gemini/config/plugins/dumbledoer/run_dumbledoer.sh <command_name>. Under NO circumstances are you allowed to invoke python3 directly or use pip install. You must rely exclusively on the run_dumbledoer.sh wrapper.

---
name: report
description: Generate the dumbledoer improvement report showing before/after changes, CodeGraph impact radius, and delta summary for all completed tasks.
---

Base directory for this skill: (project root where dumbledoer is installed)

# /dumbledoer:report — Generate Improvement Report

**References** (read before Section 1): `dumbledoer/lib/common-preamble.md`, `dumbledoer/lib/codegraph-integration.md`

**Lazy references**: `dumbledoer/lib/memory-schema.md` (load only if the repair flow triggers), `dumbledoer/lib/archive-protocol.md` (load at archived-task retrieval), `dumbledoer/lib/knowledge-protocol.md` (load at Section 3 — registry context)

## Parameters

```
/dumbledoer:report
  --format markdown|text    Optional. Output format. Default: markdown.
  --output <path>           Optional. Write report to file instead of stdout.
```

---

## Section 1 — Validate Preconditions

1. Read `memory.md`. If missing: `Error: memory.md not found. Run /dumbledoer:start first.` and stop.
2. Run the validation checklist from `lib/common-preamble.md` (on failure load `lib/memory-schema.md` for the repair flow).
3. Collect all tasks with type=`change` and status=`completed`. For tasks whose
   Checkpoint column is `archived`: load `lib/archive-protocol.md` (lazy reference),
   read their Task Details from the archive record listed in the Archive Index, and
   mark them `(archived)` in the report. If an archive file is missing: output the
   missing-archive error from `lib/archive-protocol.md` and stop. If none:
   Output exactly: `No completed changes found. Run /dumbledoer:status to see pending tasks, or /dumbledoer:resume to continue working.` and stop.

---

## Section 2 — Baseline Assessment

1. Run `codegraph status` to get current index metrics.
2. Read baseline metrics from memory.md Config section (`codegraph_baseline_symbols`, `codegraph_baseline_sync`, `codegraph_backend`).
3. Format as:

```markdown
## Baseline Assessment

- Symbols indexed at session start: {codegraph_baseline_symbols}
- CodeGraph backend: {codegraph_backend}
- Session start: {codegraph_baseline_sync}
- Current symbol count: {current from codegraph status}
- Issues identified during discovery: {from Project Goal / Scope sections in memory.md}
```

---

## Section 3 — Per-Change Sections

**Load `dumbledoer/lib/knowledge-protocol.md` now** (lazy reference). If the
knowledge registry exists, read the entries whose `task` field matches a reported
task (plus any entry they supersede) — their Rationale and supersession history
contextualize the change sections below. Registry absent or entries malformed:
apply the protocol's tolerance rules and continue without them.

For each completed `change` task (in Task ID order):

1. Read task details from memory.md Task Details subsection.
2. **Before content**: Read rollback copy from `.dumbledoer/rollbacks/{taskId}/`. If missing: `Warning: original content for {taskId} not available — before/after comparison omitted for this task.`
3. **After content**: Read current file at each output path.
4. Generate a before/after snippet: first 30 meaningful lines of each, or the key changed section.
5. Read `CodeGraph Impact` field from task details.
6. Synthesize test example: derive from conversation examples (if ingested during discovery) or from the change rationale and success criteria.
7. Format per-change section:

```markdown
### {taskId}: {title}

**What changed**: {outputs joined with comma} — {description one line}
**Rationale**: {rationale from Change Log or task description}
**Impact radius** (CodeGraph): {CodeGraph Impact field content}
**Knowledge**: {wikilink + one-line gloss of the task's registry entry, including
rolled-back/superseded status — omit this line when no entry exists}

**Before**:
> {before snippet or warning}

**After**:
> {after snippet}

**Test example**:
- Input: {representative user message or agent scenario}
- Previous behavior: {what the agent would have done before}
- New behavior: {what the agent does after this change}
- How to validate: {concrete reproduction steps}
```

---

## Section 4 — Delta Summary

Compare baseline metrics to current `codegraph status`:

```markdown
## Delta Summary

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Symbols indexed | {baseline} | {current} | {delta} |
| Files modified | 0 | {count of unique files in Change Log (applied)} | +{N} |
| Tasks completed | 0 | {count} | +{count} |
| {additional domain-specific metrics if available} | ... | ... | ... |
```

---

## Section 4a — Theoretical Token Optimization
Calculate the tokens saved during this session by DumbleDoer's dynamic tool filtering and sliced memory ingestion architecture.
1. Estimate the total number of tool calls made across all completed tasks (assume an average of 5 tool calls per `small` task, 10 for `medium`, 20 for `large`).
2. Multiply that total by `25,000` (the average input tokens saved per call by stripping unnecessary tools and truncating memory.md).
3. Format as:

```markdown
## Token Optimization

- Estimated Tool Calls Executed: {calculated_total}
- Optimization Yield: ~{calculated_total * 25000} tokens saved
- Engine Mechanism: Dynamic Tool Filtering & Sliced Memory Ingestion
```

---

## Section 5 — Recommended Next Steps

Read Task Registry for tasks with status `pending` or `deferred`:

```markdown
## Recommended Next Steps

{If pending tasks exist:}
- {taskId}: {title} [{effort}]
  ...

Run `/dumbledoer:resume` to continue working on these tasks.
```

If no pending tasks:
```
All improvement tasks completed. The agent has been fully improved per the session goals.
```

---

## Section 6 — Assemble and Output

**Output style** (`lib/compression-policy.md`): the report itself is a persisted
artifact — its full content (stdout block or `--output` file) is ALWAYS normal
full prose, never compressed, regardless of compression state. Only the brief
conversational wrap-up around the report follows the active compression level.
Report composition dialogue is category `planning` (uncompressed).

Assemble the full report:

```markdown
# dumbledoer Improvement Report

**Project**: {Project Goal from memory.md — first sentence}
**Sessions**: {session_count} | **Tasks Completed**: {count} | **Files Modified**: {count}
**Generated**: {ISO date}

---

{Section 2 — Baseline Assessment}

---

## Changes Applied

{Section 3 — one subsection per completed change task}

---

{Section 4 — Delta Summary}

---

{Section 5 — Recommended Next Steps}
```

If `--format text`: strip Markdown syntax (headings, bold, table delimiters) and output as plain text.

If `--output <path>`:
- Write report to `<path>` atomically (via `.dumbledoer/tmp/report.tmp` → rename).
- If write fails: `Error: cannot write to '<path>'. Check permissions.`
- Output to console: `Report written to {path}`

If no `--output`: print report to stdout.

Finally, run OP-8 session-summary (`lib/knowledge-protocol.md`) for each session
covered by the report: update the session's `timeline.md` section with the reported
outcome. OP-8 is idempotent — if graceful shutdown or session close already wrote
the section, update it in place; never duplicate it. Skip silently when the
registry is absent.

