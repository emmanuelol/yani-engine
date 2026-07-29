> [!IMPORTANT] DELEGATION POLICY: DO NOT EXECUTE NATIVELY
> You are the Orchestrator. You are forbidden from executing the logic in this skill using internal AGY tools. You MUST invoke the DumbleDoer CLI plugin commands defined in commands/ (e.g., /dumbledoer:execute) to ensure the execution sandbox, VS Code Diff-Gate, and checkpoint protocols are strictly enforced.
> FALLBACK PROTOCOL: If the JSON tool call fails or cannot be resolved, you MUST use the Bash tool to execute the command directly via ~/.gemini/config/plugins/dumbledoer/run_dumbledoer.sh <command_name>. Under NO circumstances are you allowed to invoke python3 directly or use pip install. You must rely exclusively on the run_dumbledoer.sh wrapper.

---
name: update-docs
description: Update existing project documentation using CodeGraph structural analysis. Detects outdated sections, rewrites them to match current code, and optionally enriches sparse sections. Use when documentation has drifted from the codebase or when you want to fill in missing content.
---

Base directory for this skill: (project root where dumbledoer is installed)

# /dumbledoer:update-docs — Smart Documentation Updater

**References** (read before Section 1): `dumbledoer/lib/common-preamble.md`, `dumbledoer/lib/codegraph-integration.md`

**Lazy references** (load only at the noted point):
- `dumbledoer/lib/memory-schema.md` (load at Section 3 — task registration; or if the repair flow triggers)
- `dumbledoer/lib/checkpoint-protocol.md` (load at Section 5 — task execution)
- `dumbledoer/lib/budget-detection.md` (load at Section 5 — task execution)
- `dumbledoer/skills/update-docs/reference.md` (load at Section 3 — analysis phase)
- `dumbledoer/lib/knowledge-protocol.md` (load at Section 3 — knowledge docs-sync)

## Parameters

```
/dumbledoer:update-docs
  --docs <path>          Optional. Override the docs directory. Defaults to docs_path in memory.md Config.
  --enrich               Optional flag. Enable enrichment of stub/empty sections (≤ 3 lines of body).
  --dry-run              Optional flag. Show planned changes without writing any files.
```

---

## Section 1 — Input Validation and Preconditions

1. Parse parameters: `DOCS_PATH` (from `--docs` or memory.md Config `docs_path`), `ENRICH_MODE`, `DRY_RUN`.

2. **Precondition P1**: Check for `memory.md` at project root.
   - If absent: output exactly `Error: memory.md not found. Run /dumbledoer:start to initialize.` and stop.

3. **Precondition P2**: Read `memory.md` in full. Run the validation checklist from `lib/common-preamble.md`.
   - If ANY rule fails: output `memory.md validation failed: Rule N — <specific description>.` and offer the FR-016 repair flow from the preamble. Execute the chosen option, then stop — let the user re-invoke.

4. **Precondition P3**: Resolve `DOCS_PATH`.
   - If `--docs` was not provided AND `docs_path` is absent or empty in memory.md Config: output exactly `Error: docs path not found. Provide --docs <path> or run /dumbledoer:start first.` and stop.
   - If `--docs` was provided but the path does not exist or is not a directory: output exactly `Error: documentation directory not found at '<path>'. Provide a valid --docs path.` and stop.

5. **Precondition P4**: Scan `DOCS_PATH` recursively for `.md` files.
   - If none found: output exactly `Warning: No documentation files found at '<DOCS_PATH>'. Nothing to update.` and stop.
   - Store the file list as `DOC_FILES`.

6. If `DRY_RUN = true`: this suppresses task registration and all file writes — Section 4 prints the planned-changes table and exits with `Dry run — no files modified.`

---

## Section 2 — CodeGraph Health Check

1. Check if `.codegraph/` exists in the project root.
2. If **absent**:
   - Output: `[yellow]CodeGraph unavailable. Proceeding with limited text-based analysis.[/yellow]`
   - Set `CODEGRAPH_AVAILABLE = false` (section-level scan only) and continue executing the skill natively.
3. If **present**: run `codegraph status`, capture symbol count and last sync as baseline metrics (reported in Section 6), set `CODEGRAPH_AVAILABLE = true`.

---

## Section 3 — Analysis and Proposal

**Read `dumbledoer/skills/update-docs/reference.md` and `dumbledoer/lib/memory-schema.md` now** (lazy references). Execute, in order:

1. **Part A** — parse `DOC_FILES` into DocSection records with `symbols_referenced` and enrichment-candidate flags.
2. **Part B** — delta analysis: derive `CHANGED_SYMBOLS` and set `update_required` per section.
3. **Knowledge docs-sync, read side** (OP-9, `lib/knowledge-protocol.md` — load now):
   if the registry exists, read entries with `created` newer than Config
   `last_knowledge_docs_sync` (`never` = all entries). Their decisions, rationale,
   and evolution notes are doc inputs that exist nowhere in the codebase: use them
   to (a) flag sections contradicted by a newer decision and (b) source rationale
   and history for updated sections. Tolerance rules apply; registry absent →
   continue with code-driven analysis only.
4. **Part C** — build the ChangeCandidate list, run per-file impact analysis, and (unless `DRY_RUN`) register one `change` task per DocFile.

**No changes case**: if no section has `update_required = true` AND none is an enrichment candidate, output exactly:
```
Documentation is already up to date.
  Files scanned: N
  Sections reviewed: M
  No updates required.
```
and stop (do NOT register tasks, do NOT update `last_docs_update`).

---

## Section 4 — User Confirmation

1. Display the planned-changes table:

   ```
   | File | Section | Change Type | Confidence |
   |------|---------|-------------|------------|
   ```

2. If `DRY_RUN = true`: output
   ```
   Dry run — no files modified.
   Run without --dry-run to apply.
   ```
   and stop.

3. Wait for confirmation:
   ```
   Apply these X changes? (yes/no/select)
     yes    — apply all
     no     — cancel
     select — choose specific changes to apply
   ```
4. `no`/`cancel`: stop with `Update cancelled.` | `select`: show numbered list, take comma-separated selection.
5. Filter `CHANGE_CANDIDATES` to confirmed items only.

---

## Section 5 — Task Execution

**Load `dumbledoer/lib/checkpoint-protocol.md` and `dumbledoer/lib/budget-detection.md` now** (lazy references).

**Output style** (`lib/compression-policy.md`): all documentation content written
to disk is a persisted artifact — ALWAYS normal full prose, never compressed.
Analysis/proposal dialogue (Sections 3–4) is category `planning` (uncompressed);
per-task conversational progress replies follow the task's category.

For each confirmed task, in dependency order:

1. **Budget check** before starting each task (`lib/budget-detection.md`). If threshold crossed: graceful shutdown — do NOT start the next task. NOTE: `last_docs_update` is NOT written during shutdown; only in Section 6.
2. Claim the task: status `in_progress`, Owner = current session ID (dual-update convention).
3. Execute each ChangeCandidate via **Part D** of `reference.md` (10-step data flow: pre-write analysis + 6-step checkpoint protocol + content assembly).
4. After each task: verify Success Criteria (section updated as planned; file is parseable Markdown). Pass → `completed`. Fail → `in_progress` with error note; retry once; if still failing, flag for the user.
5. **Capture the learning** (OP-4 capture-success, `lib/knowledge-protocol.md`): on
   `completed`, record what drifted and which update/enrichment heuristics worked,
   with the task ref — before starting the next task. Skip (with a Notes note) when
   the task taught nothing durable.
6. Budget check after each task completes.

---

## Section 6 — Session Close

Execute ONLY when ALL tasks have completed. (If interrupted, the session handoff summary applies — `lib/budget-detection.md`.)

1. Set all tasks from this run to `completed` in memory.md.
2. **Write `last_docs_update`** (ISO 8601) and `last_docs_update_session` (current session ID) to memory.md Config — only here, after full completion.
3. **Knowledge docs-sync, write side** (OP-9): set `last_knowledge_docs_sync` to the
   run timestamp in memory.md Config — only here, after full completion. An
   interrupted run leaves it untouched so the next run re-reads the same window.
4. Update Session Log: End Time, Outcome = `completed`.
5. Write `.dumbledoer/sessions/{sessionId}.json` with execution trace.
6. Run `codegraph status` and note final symbol count vs the Section 2 baseline.
7. Output the success summary:
   ```
   Documentation update complete.
     Files scanned: {N}
     Sections reviewed: {M}
     Sections updated: {count}
     Sections enriched: {count; 0 if --enrich not set}
     Sections flagged for review: {count of remove-stale sections}
     Files modified: {list of relative paths}

   Run /dumbledoer:status to see the full task log.
   Run /dumbledoer:rollback to undo changes.
   ```

