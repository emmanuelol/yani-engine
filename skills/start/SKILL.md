> [!IMPORTANT] DELEGATION POLICY: DO NOT EXECUTE NATIVELY
> You are the Orchestrator. You are forbidden from executing the logic in this skill using internal AGY tools. You MUST invoke the DumbleDoer CLI plugin commands defined in commands/ (e.g., /dumbledoer:execute) to ensure the execution sandbox, VS Code Diff-Gate, and checkpoint protocols are strictly enforced.

---
name: start
description: Start a new agent improvement session with discovery Q&A, CodeGraph analysis, and task execution. Use when beginning a new dumbledoer improvement project.
---

Base directory for this skill: (project root where dumbledoer is installed)

# /dumbledoer:start — Start an Agent Improvement Session

**References** (read before Section 1): `dumbledoer/lib/common-preamble.md`, `dumbledoer/lib/memory-schema.md`, `dumbledoer/lib/codegraph-integration.md`, `dumbledoer/lib/budget-detection.md`, `dumbledoer/lib/compression-policy.md`

**Lazy references** (load only at the noted point):
- `dumbledoer/lib/knowledge-protocol.md` (load at Section 4a — knowledge registry)
- `dumbledoer/lib/checkpoint-protocol.md` (load at Section 8 — task execution)
- `dumbledoer/templates/memory-template.md` (load at Section 6)
- `dumbledoer/templates/session-handoff-template.md` (load at Section 9 — graceful shutdown)
- `dumbledoer/lib/archive-protocol.md` (load at Section 10 — session close)
- `dumbledoer/lib/memory-archive-prompt.md` (load at Section 10 — session close prompt)

## Parameters

```
/dumbledoer:start
  --docs <path>                Required. Path to documentation directory.
  --project <path>             Optional. Path to project.md high-level description.
  --examples <dir>             Optional. Directory of conversation example files (any text format).
  --requirements <path>        Optional. Path to requirements or user-story document.
  --budget-threshold <pct>     Optional. Override default 80% shutdown threshold (1–99).
  --budget-limit <tokens>      Optional. Override default 100000 token budget.
  --dry-run                    Optional flag. Preview mode: run discovery and register
                               the task plan, then stop before executing anything.
  --no-compression             Optional flag. Disable caveman output compression for
                               this session (compression is ON by default).
```

---

## Section 1 — Input Validation

1. Parse all parameters from the command invocation.
2. Verify `--docs` path exists and is a readable directory.
   - If not: output exactly `Error: documentation directory not found at '<path>'. Provide a valid --docs path.` and stop.
3. Check for existing `memory.md` at project root:
   - If it exists: run Section 2a (memory.md pre-check) before proceeding.
   - If it does not exist: proceed to Section 3.
4. Validate `--budget-threshold` is an integer between 1 and 99.
   - If invalid: output `Error: --budget-threshold must be an integer between 1 and 99.` and stop.
5. Resolve the session's compression state (`lib/compression-policy.md` — the
   caveman ruleset is bundled at `skills/caveman/SKILL.md`, nothing to install
   or detect):
   - If `--no-compression` was passed: set the session compression state to
     disabled and output exactly: `Output compression disabled for this session.`
   - Otherwise: output exactly:
     ```
     Output compression (caveman) is ON for this session — full for simple tasks, lite for complex tasks, off for planning and documents. Reply 'no compression' (or pass --no-compression) to disable.
     ```
     If the user replies `no compression` at the first prompt, treat it exactly
     like `--no-compression` (one-line acknowledgement, state disabled).
   - The resolved state (`true`/`false`) is substituted into memory.md in
     Section 6. Mid-session toggles follow `lib/compression-policy.md`.

### Section 2a — memory.md Pre-Check

1. Read `memory.md` in full.
2. Run the validation checklist from `lib/common-preamble.md`.
3. If ALL rules pass:
   - Output exactly: `Error: memory.md already exists. Run /dumbledoer:resume to continue, or /dumbledoer:status to inspect current state.`
   - Stop.
4. If ANY rule fails (malformed):
   - Output: `memory.md validation failed: Rule N — <description of which rule failed and what value is invalid>.`
   - Offer the user: `(a) Reset state to the last valid checkpoint in Checkpoint Registry. (b) Archive memory.md as memory.md.corrupted.{timestamp} and start a fresh session.`
   - Wait for user choice. Execute chosen option. Stop (do not continue to Section 3 — let user re-invoke).

---

## Section 3 — CodeGraph Index Setup

The CodeGraph MCP server ships with the plugin (`dumbledoer/.mcp.json` runs
`npx -y @colbymchenry/codegraph serve --mcp`) — there is nothing to install and
no Gemini Code restart. Only the project INDEX may need to be built:

1. Resolve the CLI: use the `codegraph` binary if on PATH, otherwise
   `npx -y @colbymchenry/codegraph` (no install needed).
2. If `.codegraph/` does not exist in the project root (the parent directory of
   the `--docs` path): run `codegraph init -i` there (via the resolved CLI) to
   create it and build the index.
   - If init fails: output `Warning: CodeGraph index initialization failed. Continuing without impact analysis. Run 'codegraph init -i' manually from the project root.` and proceed (non-fatal).
3. Run `codegraph status` and capture: symbol count, last sync time, backend type.
   Note these as baseline metrics (used in Section 6 and by `/dumbledoer:report`).

---

## Section 4 — Ingest Inputs

Read all provided input files as plain text (any format accepted, no schema required):

1. Read all files recursively from `--docs` directory.
2. If `--project` provided: read the file.
3. If `--examples` provided: read all files in the directory recursively.
4. If `--requirements` provided: read the file.
5. Explicitly detect if `Dockerfile` or `docker-compose.yml` exists in the project root.

Summarize the ingested content internally to understand the agent's purpose, existing
behavior, and any stated improvement goals.

---

## Section 4a — Knowledge Registry

**Load `dumbledoer/lib/knowledge-protocol.md` now** (lazy reference).

1. Instruct AGY to check for `knowledge/index.md` on startup.
2. If absent, instruct AGY to use `write_file_with_review` to create it from `templates/knowledge-index-template.md`.
3. If present, instruct AGY to selectively read ONLY `index.md` and active `failure` or `constraint` entries matching the current project goal during discovery.
4. Carry the loaded knowledge into Sections 5–7: cite relevant prior decisions,
   constraints, and failures during discovery and planning instead of re-asking
   the user for history.

---

## Section 5 — Discovery Q&A

Conduct an interactive Q&A session with the user to clarify improvement goals.

Ask the user about:
1. What specific behaviors or outcomes need improvement (accuracy, tone, tool usage, instruction-following, etc.).
2. Which components are in scope: system prompts, tool call definitions, few-shot examples, conversation flow, code files.
3. Success criteria: how will we know improvements worked.
4. Constraints: what must not change.
5. If containers are detected, ask the user if DumbleDoer should use the project's native containers for the execution sandbox, and if the user wants DumbleDoer to audit and optimize their Docker configurations.

Based on the Q&A results, compose:
- **Project Goal**: one paragraph summarizing the improvement objective.
- **Scope**: bullet list of in-scope components (file paths or component types).

---

## Section 6 — Initialize memory.md

1. Generate a session ID (format and collision rules: `lib/common-preamble.md`).
2. Create `.dumbledoer/sessions/`, `.dumbledoer/checkpoints/`, `.dumbledoer/rollbacks/`, `.dumbledoer/tmp/` directories.
3. Write `memory.md` from `templates/memory-template.md`, substituting:
   - `{{DATE}}` → today's date (YYYY-MM-DD)
   - `{{PROJECT_GOAL}}` → Project Goal from Section 5
   - `{{SCOPE_ITEMS}}` → Scope bullets from Section 5
   - `budget_limit` → `--budget-limit` value or 100000
   - `budget_threshold_pct` → `--budget-threshold` value or 80
   - `session_count` → 1
   - `{{COMPRESSION_ENABLED}}` → the compression state resolved in Section 1
     step 5 (`true` unless the user opted out)
4. Append first Session Log row: `| {sessionId} | {ISO startTime} | — | — | active |`
5. Write baseline CodeGraph metrics (from Section 3) to Config section:
   ```
   - codegraph_baseline_symbols: N
   - codegraph_baseline_sync: {ISO timestamp}
   - codegraph_backend: native|wasm
   ```

**CRITICAL**: `memory.md` must be fully written before any task is registered or any
file in the user's project is modified.

---

## Section 6b — Edge Case Q&A

Before decomposing tasks, identify 3-5 edge cases based on the user's prompt.
1. Ask the user how to handle them.
2. Write the results to the `## Edge Case Coverage` table in `memory.md`.

---

## Section 7 — Task Decomposition and Registration

Based on the discovery Q&A and ingested inputs, decompose all improvement work into
atomic tasks.

For each task:
1. Assign a Task ID (format and generation: `lib/common-preamble.md`).
2. Determine type: `analysis`, `change`, `validation`, or `report`.
3. Set estimated effort: `small`, `medium`, or `large`.
4. Identify dependencies (which tasks must complete first).
5. Determine if parallelizable (no overlapping output files with sibling tasks).
6. **Consult the knowledge registry** (OP-3, `lib/knowledge-protocol.md`): compare the
   task's approach against loaded `failure` entries (same component, technique, or
   file set) and `constraint` entries. On a failure match, present the
   `Prior failure on record: …` prompt and wait for the user's choice (proceed /
   adapt / skip) — never adopt a recorded-failed approach silently. If the task's
   topic is outside the loaded set, lazily load matching active entries first.
7. For `change` tasks: run `codegraph_impact` on the primary symbol or file to be
   modified. Log the result in the task's CodeGraph Impact field.
8. **Tag external dependencies** (`lib/context7-protocol.md`): note in the task
   whether its change or analysis depends on an external library, framework, SDK,
   or CLI tool API — name the libraries when known. This tag drives the
   documentation lookup (or its zero-latency skip) at execution time; the
   executing agent re-checks before the first dependent change.
9. Register the task in `memory.md` (dual-update convention, `lib/common-preamble.md`)
   BEFORE executing it.

Always include a final `report` task (e.g., `T-NNN: Generate improvement report`).

**Integrity validation (before any task is written)**: run the registration-time
Rules 7–9 from `lib/memory-schema.md` against the complete proposed plan (uniqueness,
referential completeness, acyclicity). On any failure: print the rule's exact error,
register nothing, and re-enter plan refinement in this session — present the corrected
plan again before retrying registration.

Confirm the full task plan with the user before proceeding to execution.

### Preview exit (--dry-run)

If `--dry-run` was passed, stop here instead of proceeding to Section 8:

1. Print the full registered plan (Task IDs, titles, types, dependencies, efforts)
   and the total budget estimate (`lib/budget-detection.md` per-operation costs).
2. Close the session: Session Log End Time = now, Outcome = `completed`; increment
   `session_count`; write `.dumbledoer/sessions/{sessionId}.json`; run the
   archive check (Section 10 step 6). Skip OP-8 session-summary — a dry run
   captures no knowledge entries.
3. Do NOT show the execute prompt. Output exactly:
   ```
   Plan preview complete — no tasks were executed.
   The plan is saved in memory.md. Run /dumbledoer:execute to run it,
   or /dumbledoer:status to review it. Discovery will not be repeated.
   ```
4. Guarantee: no file outside `memory.md`, `.dumbledoer/`, and `{knowledge_path}`
   (empty-registry initialization from Section 4a only — no entries are captured
   during a dry run) has been created or modified during this session.

---

## Section 8 — Task Execution

**Load `dumbledoer/lib/checkpoint-protocol.md` now** (lazy reference).

Execute tasks in dependency order. For parallelizable tasks, spawn sub-agents.

For each task claimed:
1. Update task status to `in_progress` and set Owner to current session ID in `memory.md`.
2. Classify the task per `lib/compression-policy.md` (type + effort → `simple` or
   `complex`) and spawn a sub-agent (or execute inline for small analysis tasks)
   following all rules in `lib/codegraph-integration.md`:
   - `simple` tasks: request the standard model tier (`gemini-2.0-flash`) at spawn.
   - `complex` tasks: request the premium model tier (`gemini-2.0-pro`) at spawn.
   - Include the task's compression level in the sub-agent prompt (template below).
   - If the requested tier is unavailable, spawn on the session default model and
     output the one-time fallback notice from `lib/compression-policy.md`.
3. For `change` tasks: follow ALL 6 steps of `lib/checkpoint-protocol.md` exactly.
4. After each task completes: verify against its Success Criteria. If pass, set status `completed`. If fail, set status `in_progress` with a note and retry or flag for user.
5. **Capture the learning** (OP-4 capture-success, `lib/knowledge-protocol.md`): on
   `completed`, write the knowledge entry (what changed, why it worked, CodeGraph
   impact summary) plus its index.md row — including the OP-7 supersession check —
   BEFORE claiming the next task. On a task abandoned as failed, run OP-5
   capture-failure instead. If the task taught nothing durable, skip capture and
   note the skip in the task's Notes field.
6. Check budget after each task using algorithm in `lib/budget-detection.md`. If threshold crossed, trigger graceful shutdown (Section 9).

**Manual capture**: at ANY point in the session, if the user states a learning to
record, run OP-6 capture-manual — create the entry, confirm in one line
(`Recorded [[K-NNN-slug]] ({type}): {title}.`), and return to the task in progress.

### Sub-Agent Instruction Template

When spawning a sub-agent for a task, include in the prompt:

> This project has CodeGraph initialized (.codegraph/ exists). You are executing task
> {taskId}: {title}.
>
> **Mandatory rules**:
> 1. Read `dumbledoer/lib/codegraph-integration.md` before modifying any file.
> 2. Follow the 10-step data flow for change tasks exactly.
> 3. Follow `dumbledoer/lib/checkpoint-protocol.md` for every file write.
> 4. Log your codegraph_impact result to memory.md task {taskId} CodeGraph Impact field.
> 5. Do not modify any file listed in another in-progress task's Outputs.
> 6. Output compression: render your conversational replies at caveman level
>    `{full|lite|off}` per `dumbledoer/lib/compression-policy.md`. Code, file
>    paths, identifiers, commands, URLs, and numeric values are byte-preserved at
>    every level. ALL file writes (memory.md, knowledge entries, docs, any
>    artifact) are normal full prose regardless of level.
> 7. Documentation lookup: this task {is|is not} tagged with external
>    dependencies {(libraries: …)}. If tagged (or if a dependency emerges while
>    working), follow `dumbledoer/lib/context7-protocol.md` BEFORE the first
>    dependent change — Step 0 of the 10-step data flow — and record the outcome
>    in the task's Notes field.
>
> When done, update task {taskId} status to `completed` in memory.md and write your
> session end to the Session Log.

---

## Section 9 — Graceful Shutdown

Triggered when `tokens_estimated >= shutdown_threshold` (see `lib/budget-detection.md`).

1. Complete the current atomic step (do not abandon mid-checkpoint-protocol).
2. Ensure the in-progress task has a valid checkpoint.
3. Set task status to `interrupted`; clear Owner.
4. Update Session Log: set End Time, set Outcome to `interrupted-budget`.
5. Fill `templates/session-handoff-template.md` with all required fields.
6. Append Session Handoff Summary to `memory.md` (after Open Questions section).
7. Run OP-8 session-summary (`lib/knowledge-protocol.md`): write this session's
   timeline.md section (goal, outcome, entry wikilinks). Entries themselves are
   already on disk — capture is incremental, so no per-entry catch-up is needed here.
8. Write `.dumbledoer/sessions/{sessionId}.json` with full trace.
9. Output the Session Handoff Summary as the final command output.

---

## Section 10 — Normal Session Close

When all selected tasks are complete (or user stops the session):

1. Set all completed tasks to `completed` in memory.md.
2. Update Session Log: End Time = now, Outcome = `completed`.
3. Run OP-8 session-summary (`lib/knowledge-protocol.md`): write or update this
   session's timeline.md section (idempotent — a later /dumbledoer:report run
   updates the same section, never duplicates it).
4. Increment `session_count` in Config.
5. Write `.dumbledoer/sessions/{sessionId}.json`.
6. **Archive check**: load `lib/archive-protocol.md` (lazy reference) and run the
   archive trigger. If sessions are eligible, archive them per the protocol and
   report what was archived. (Skipped during graceful shutdown — Section 9 — to
   preserve remaining budget; the next normal close catches up.)
7. **Memory archive prompt**: load `lib/memory-archive-prompt.md` (lazy reference)
   and run the memory archive prompt protocol. If the trigger condition is met
   (memory.md exists with Session Log entries and this is not a dry-run), show the
   prompt and execute the user's chosen action (archive or skip). If the condition
   is not met, skip silently.
8. Generate and output a brief session summary:
   ```
   Session {sessionId} complete.
   Tasks completed: {N} | Tasks remaining: {M}
   Run /dumbledoer:status for full details.
   Run /dumbledoer:report to generate the improvement report.
   ```

