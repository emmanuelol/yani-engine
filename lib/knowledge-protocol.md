# knowledge-protocol: Cross-Session Knowledge Registry Operations

The knowledge registry is the project's durable memory across sessions: what worked,
what didn't, and why. It lives in the TARGET project at `{knowledge_path}` (memory.md
Config, default `knowledge/`) and is never archived — unlike session state in
`memory.md`, registry entries persist for the life of the project.

Every registry read or write MUST go through the operations below. Commands MUST NOT
manipulate registry files ad hoc.

Contract: `specs/015-knowledge-registry/contracts/knowledge-protocol-contract.md` ·
Tests: `tests/contract/test-knowledge-contract.md`

---

## Registry Layout

```
{knowledge_path}/
├── index.md                  # entries grouped by type (template: knowledge-index-template.md)
├── timeline.md               # reverse-chronological session sections
└── entries/
    └── K-NNN-short-slug.md   # one note per entry (template: knowledge-entry-template.md)
```

**Entry frontmatter** — required: `id` (K-NNN), `title`, `type` (`decision` |
`success` | `failure` | `constraint` | `insight`), `status` (`active` |
`superseded`), `created` (ISO 8601), `session` (S-ID or `manual`), `tags`
(always includes `knowledge-registry`). Optional: `task`, `supersedes`,
`superseded_by`.

**K-NNN allocation**: highest existing ID across `entries/` filenames and
frontmatter, +1, zero-padded 3 digits (extend to 4 past 999) — same convention
as Task IDs in `lib/common-preamble.md`.

## Obsidian Conventions

Write all registry notes as Obsidian Flavored Markdown. The `obsidian-markdown`
skill is BUNDLED with the plugin (`dumbledoer/skills/obsidian-markdown/`, vendored
from kepano/obsidian-skills, MIT) — follow it for syntax details. The summary
below states the same conventions for quick reference:

- **Properties**: YAML frontmatter between `---` fences at the very top; lists in
  `[a, b]` form; quote values containing `[[` (e.g., `supersedes: "[[K-006-slug]]"`).
- **Wikilinks**: `[[filename-without-extension]]` or `[[file|display text]]`;
  escape `|` as `\|` inside tables.
- **Callouts**: `> [!warning] Title` followed by `> ` body lines.

---

## Operations

### OP-1 — initialize

**Caller**: start (only command allowed to create the registry).

When `{knowledge_path}` is absent or empty: create the directory and `entries/`,
write `index.md` and `timeline.md` from `templates/knowledge-index-template.md`,
record `knowledge_path` in memory.md Config, and print exactly:

```
Knowledge registry initialized at '{knowledge_path}'.
```

Then proceed with normal discovery — there is no prior knowledge to cite.

### OP-2 — selective-load

**Callers**: start (after docs ingestion), resume (after memory.md validation).

Read, in order — and nothing else at startup:

1. `index.md` in full.
2. The 3 most recent session sections of `timeline.md`.
3. Entry notes where `status: active` AND (`type` is `failure` or `constraint`,
   OR frontmatter `tags` overlap keywords extracted from the stated session goal).

All other entries load lazily when a topic match arises (OP-3). This keeps startup
cost flat as the registry grows. Print exactly:

```
Knowledge registry: {N} entries loaded ({F} failures, {C} constraints, {M} goal-matched) of {T} total.
```

Count each loaded entry once, in the first matching category (failure > constraint
> goal-matched). `{T}` counts parseable entries only.

**Tolerance** (applies to every operation that reads entries):
- Unparseable entry (broken frontmatter, missing required field):

  ```
  Warning: knowledge entry '{relative/path}' could not be parsed ({reason}). Entry skipped; fix or remove it.
  ```

  One warning per file per session. Never abort.
- Duplicate `id`: use the newest by `created`; print:

  ```
  Warning: duplicate knowledge ID '{id}' — using newest by created date.
  ```

- Missing optional metadata: accept silently.
- Registry absent and caller is not start: print a one-line note that the registry
  is missing and that `/dumbledoer:start` will create it; continue as a no-op.

### OP-3 — consult

**Callers**: start (task decomposition), resume (interrupted-task resolution).

Before adopting any proposed approach, compare it against loaded `failure` entries
(same component, same technique, or same file set). On overlap, present — and do
NOT silently adopt the approach:

```
Prior failure on record: [[{K-NNN-slug}]] — {title} ({session}). Reason: {one-line rationale}. Proceed anyway, adapt, or skip?
```

`constraint` entries are binding context: surface any constraint the approach
would violate. When decomposition raises a topic not in the loaded set, lazily
load active entries whose tags match before finalizing that task.

In resume, recorded failures and retry conditions inform the resume-vs-rollback
recommendation for interrupted tasks (cite the entry when they change the advice).

### OP-4 — capture-success

**Callers**: start (task completion — checkpoint protocol Step 6), update-docs
(doc task completion).

When a task completes and validates:

1. Allocate the next K-NNN; create `entries/K-NNN-{slug}.md` from
   `templates/knowledge-entry-template.md`: `type: success`, what changed
   (Description), why it worked (Rationale), files touched + CodeGraph impact
   summary (Context), `session`/`task` refs.
2. Run the OP-7 supersession check.
3. Update `index.md` in the same operation (Registry Dual-Update Rule below).

The entry MUST be on disk before the next task begins — capture is incremental;
an interrupted session loses at most the in-flight step (CT-KNOW-PERSIST-01).

Routine completions yield one concise entry; do not pad. Skip capture entirely
only when a task taught nothing durable (e.g., a no-op validation), and note the
skip in the task's Notes field.

### OP-5 — capture-failure

**Callers**: rollback (after rollback completes), start (task abandoned or failed).

Two cases:

- **No entry exists for the task**: create one — `type: failure`, the attempted
  approach (Description), why it failed (Rationale), and `## Retry Conditions`
  (conditions under which the approach may be retried; "none known" is valid).
- **A success entry exists for the task** (rollback after capture): rewrite that
  SAME note in place — flip `type` to `failure`, keep `id` and filename, append:

  ```
  > [!warning] Rolled back
  > Rolled back in {sessionId} ({timestamp}): {reason}.
  ```

  Do not create a second entry.

Then update `index.md` (regroup if the type changed) and append a reversal line to
the current session's `timeline.md` section.

### OP-6 — capture-manual

**Callers**: any command, when the user states a learning to record.

Create the entry immediately — `type` as stated (default `insight`), `session` =
current session ID (or `manual` outside a session), omit `task` unless stated —
update `index.md`, confirm in one line, and return to the task in progress
without further discussion:

```
Recorded [[{K-NNN-slug}]] ({type}): {title}.
```

### OP-7 — supersede

**Caller**: any capture operation whose new learning contradicts an active entry.

Set on the new entry: `supersedes: "[[{old-slug}]]"`. Set on the old entry:
`status: superseded` and `superseded_by: "[[{new-slug}]]"`. Update both index rows.
NEVER delete the old note — contradicted knowledge is history, not garbage.
When loading, prefer the newest `active` entry on any topic.

### OP-8 — session-summary

**Callers**: start/resume (graceful shutdown, alongside the session handoff),
report (report generation).

Prepend (newest first) a section to `timeline.md`:

```
## {sessionId} — {date}

Goal: {one-line goal}. Outcome: {Session Log outcome value}.

- [[{K-NNN-slug}]] — {one-line gloss}   (one line per entry captured this session)

Reversal: {task ID and reason}           (only if a rollback occurred this session)
```

**Idempotent per session**: if a section for this session ID already exists,
update it in place — never duplicate it (CT-KNOW-SUMMARY-02).

### OP-9 — docs-sync

**Caller**: update-docs.

- **At run start**: read entries with `created` newer than Config
  `last_knowledge_docs_sync` (value `never` means all entries). Feed their
  decisions, rationale, and evolution notes into the documentation updates —
  this is the knowledge that exists nowhere in the codebase.
- **On successful completion only**: set `last_knowledge_docs_sync` to the run
  timestamp in memory.md Config. An interrupted run leaves it untouched
  (CT-KNOW-DOCSYNC-02), so the next run re-reads the window.

---

## Registry Dual-Update Rule

The entry note and its `index.md` row are two views of one record (extension of
the Dual-Update Convention in `lib/common-preamble.md`). Every capture or
supersession writes both in the same operation; OP-5 and OP-8 additionally write
`timeline.md`. Never let them diverge.

## Invariants

1. The harness never deletes a registry file.
2. Registry problems never abort a session — worst case is a warning and degraded
   knowledge context.
3. Only start creates the registry (OP-1); every other caller no-ops gracefully
   when it is absent.
4. Durable learnings live in the registry; session-scoped working data stays in
   `memory.md`. Do not duplicate one into the other.
5. All notes are valid Obsidian Flavored Markdown per the conventions above.

