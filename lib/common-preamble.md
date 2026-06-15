# common-preamble: Shared Rules for All dumbledoer Commands

Every dumbledoer command MUST read this file before Section 1 of its SKILL.md.
This file is the single authoritative statement of the rules below. Command files
MUST NOT restate them; if a command file ever conflicts with this preamble, the
preamble wins.

---

## Validation Checklist (run on every session start)

Run these checks against `memory.md`. Full definitions: `lib/memory-schema.md`.

- **Rule 1** — Every Task Registry row has a matching `### T-NNN:` Task Details subsection (Task IDs listed in the Archive Index count as satisfied).
- **Rule 2** — No task is `in_progress` without a non-empty `owner`.
- **Rule 3** — Every `owner` value matches a Session ID in the Session Log.
- **Rule 4** — Every non-`none` checkpoint in Task Registry matches a Checkpoint Registry row (or `archived`, with the session listed in the Archive Index).
- **Rule 5** — `budget_threshold_pct` is an integer 1–99.
- **Rule 6** — Every Edge Case Coverage row with disposition `addressed` has at least one valid Task ID after plan generation (`TBD` invalid after plan generation).

**Registration-time rules** (Rules 7–9: Task ID uniqueness, dependency referential
completeness, acyclicity) apply whenever ANY command registers new tasks — start,
iterate, update-docs, or future task-registering commands — see `lib/memory-schema.md`
for the rules and exact error texts. Rejection is atomic (nothing registered) and
returns the command to plan refinement. They are NOT run on session start.

**On violation of Rules 1–6**: halt, name the failed rule, display the offending
field values, and offer the FR-016 repair flow (`lib/memory-schema.md`):
(a) reset to last valid checkpoint, or (b) archive the corrupted file as
`memory.md.corrupted.{timestamp}` and start fresh.

---

## ID Formats

| ID | Format | Generation |
|---|---|---|
| Session | `S-{YYYYMMDD-HHmmss}` | Timestamp to the second; on collision append `-2`, `-3`, … |
| Task | `T-NNN` zero-padded 3-digit; extend to 4 digits past 999 | Highest existing ID in Task Registry + Archive Index, +1 |
| Checkpoint | `{taskId}-step{N}-{sessionId}` | Step index is 1-based per task |
| Edge Case | `EC-NNN` zero-padded 3-digit | Highest existing ID in Edge Case Coverage, +1 |
| Knowledge Entry | `K-NNN` zero-padded 3-digit; extend to 4 digits past 999 | Highest existing ID in `{knowledge_path}/entries/` (filenames + frontmatter), +1 — see `lib/knowledge-protocol.md` |

---

## Dual-Update Convention

The Task Registry row and the corresponding Task Details subsection are two views
of one record. Any write that changes one MUST change the other in the same
`memory.md` write. Never let them diverge.

The same rule extends to the knowledge registry: a knowledge entry note and its
`index.md` row are one record — every capture or supersession writes both in the
same operation (`lib/knowledge-protocol.md`, Registry Dual-Update Rule).

---

## Compression Policy & Documentation Lookup

Two plugin-wide protocols apply to every command:

- **Output compression** (`lib/compression-policy.md`): governs the style of ALL
  conversational output — category→level mapping, session state, toggles, and
  exclusions. Read it before producing any user-facing response.
- **Documentation lookup** (`lib/context7-protocol.md`): governs when a task that
  depends on an external library/framework/SDK API must consult current
  documentation before proposing or executing changes. Load it when claiming any
  task tagged with external dependencies.

As with all preamble-referenced rules, these files are the single authoritative
statements of their protocols; command files reference them and MUST NOT restate
their rules.

---

## Error Message Style

All user-facing errors are human-readable, name the offending value, state what
was (not) changed, and end with an actionable next step. No raw stack traces.

