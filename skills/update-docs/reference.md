# update-docs reference: Analysis and Execution Detail

Companion to `skills/update-docs/SKILL.md`. Read this file when SKILL.md Section 3
begins — not at invocation. Parts A–C drive the analysis/proposal phase; Part D
drives per-task execution.

---

## Part A — Doc Discovery and Section Parsing

For each file in `DOC_FILES`:

1. Read the file content in full.
2. Parse into a list of **DocSection** records (per `specs/006-codegraph-docs-update/data-model.md`):
   - A DocSection starts at any Markdown heading (`#` through `######`).
   - Its `body` is all content between this heading and the next heading of equal or higher level (or end of file).
   - Set `line_start` and `line_end` (1-based).
3. For each DocSection, extract `symbols_referenced`:
   - All backtick-delimited tokens in the body (inline code).
   - All wikilinks (`[[symbol]]` or `[[symbol|display]]`) — extract the symbol part.
   - All identifiers inside code fences.
   - Deduplicate into a string list.
4. Enrichment candidate detection (only when `ENRICH_MODE = true`):
   - `is_empty = true` if `body` has 0 non-empty lines.
   - `is_stub = true` if `body` has 1–3 non-empty lines.
   - `enrichment_candidate = (ENRICH_MODE AND (is_empty OR is_stub))`.

---

## Part B — Delta Analysis

**Goal**: Determine which DocSections have `update_required = true`.

### B1: Get changed files since last update

1. Read `last_docs_update` from memory.md Config.
2. If `last_docs_update` is set AND `CODEGRAPH_AVAILABLE = true`:
   - Run: `git log --name-only --pretty=format: --since="<last_docs_update>"`
   - Parse output into `CHANGED_FILES`.
   - If the git command fails (no repo, error): fall back to full scan (step 3).
3. If `last_docs_update` is null OR git failed:
   - Set `CHANGED_FILES` to all files returned by `codegraph_files` (full scan mode).

### B2: Map changed files to symbols

1. If `CODEGRAPH_AVAILABLE = true`: for each file in `CHANGED_FILES`, run `codegraph_search` with the filename; accumulate found symbols into `CHANGED_SYMBOLS`.
2. If `CODEGRAPH_AVAILABLE = false`: set `CHANGED_SYMBOLS` to empty.

### B3: Determine update_required per DocSection

1. If `CODEGRAPH_AVAILABLE = true`: if any symbol in `section.symbols_referenced` appears in `CHANGED_SYMBOLS`, set `update_required = true` with `update_reason = "Symbol(s) referenced in this section have changed: <symbol list>"`.
2. If `CODEGRAPH_AVAILABLE = false`: flag all sections with non-empty `symbols_referenced` as `update_required = true` with `update_reason = "CodeGraph unavailable; section references code symbols that may have changed"`.
3. Enrichment candidates are marked separately — they do not require `update_required = true` (they become `change_type = enrich` in Part C regardless).

---

## Part C — ChangeCandidate Generation, Impact, Registration

### C1: Build ChangeCandidate list

For each DocSection where `update_required = true`:
1. Run `codegraph_search` on each symbol in `symbols_referenced` to verify it still exists.
   - Symbol gone: `change_type = remove-stale`; `confidence = high`.
   - Symbol exists: run `codegraph_node` for current signature/description; draft `proposed_body` from it.
     - Context changed: `change_type = update`, `confidence = high`.
     - Uncertain: `change_type = update`, `confidence = inferred`.
2. Set `codegraph_source = "codegraph_node({symbol})"`.

For each DocSection where `enrichment_candidate = true`:
1. Run `codegraph_context` with the section heading as the query topic.
2. Draft `proposed_body` from the returned context.
3. `change_type = enrich`, `confidence = inferred`, `codegraph_source = "codegraph_context({heading})"`.

**Stale reference handling**: for `change_type = remove-stale`, do NOT auto-propose deletion. Set `proposed_body` to:
```
> ⚠️ **Review required**: The symbol `{symbol}` referenced here was not found in the current codebase. This section may be outdated. Please verify and update manually.

{original_body}
```

### C2: Impact analysis (mandatory before registration)

For each unique DocFile with ≥ 1 ChangeCandidate:
1. Run `codegraph_impact` on the doc file path (doc files are typically sinks — expect 0–2 affected symbols).
2. Log the result to the task's CodeGraph Impact field in memory.md Task Details.
3. If impact radius > 20 symbols: alert and wait for user confirmation before proceeding.

### C3: Task registration (skip if DRY_RUN = true)

1. For each unique DocFile with ≥ 1 ChangeCandidate, create one `change` task:
   - Title: `Update docs: {relative path of DocFile}` | Type: `change` | Status: `pending`
   - Outputs: `[relative path of DocFile]` | Estimated Effort: `small`
   - CodeGraph Impact: from C2.
2. Registration follows the registration-time integrity rules (Rules 7–9, `lib/memory-schema.md`) and the dual-update convention (`lib/common-preamble.md`).
3. All tasks MUST be fully registered BEFORE any file is written (Guarantee G3).

---

## Part D — Per-Task Execution Data Flow

For each ChangeCandidate in the task's DocFile, execute the **10-step CodeGraph data flow** (`lib/codegraph-integration.md`):

**Steps 1–3: Pre-write analysis**
- `codegraph_search("{symbol}")` → confirm target
- `codegraph_impact("{doc file path}", depth=3)` → blast radius
- Log impact summary to memory.md Task Details

**Steps 4–10: Checkpoint protocol** (`lib/checkpoint-protocol.md`, 6 steps)
- Step 4 (= checkpoint 1): copy original to `.yani/rollbacks/{taskId}/{encodedPath}`
- Step 5 (= checkpoint 2): append `planned` entry to Change Log
- Step 6 (= checkpoint 3): write checkpoint JSON to `.yani/checkpoints/{checkpointId}.json`
- Step 7 (= checkpoint 4): write new content to `.yani/tmp/{filename}.tmp`
- Step 8 (= checkpoint 5): atomic rename `.tmp` → target path
- Steps 9–10 (= checkpoint 6): update Change Log to `applied`; run `codegraph_affected([modified doc file])` and log affected test files in task Notes

**Content assembly for Step 7**:
- Read the original doc file content.
- For each ChangeCandidate in this file:
  - `update`: replace `section.body` with `proposed_body`.
  - `enrich`: replace `section.body` with:
    ```
    <!-- kpw:enriched -->
    {proposed_body}
    <!-- /kpw:enriched -->
    ```
  - `remove-stale`: replace `section.body` with the flagged version from C1.
- Preserve all other sections exactly as-is; write the assembled full file to the `.tmp`.

