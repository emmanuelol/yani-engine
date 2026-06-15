---
description: Show the dumbledoer Task Registry, session summary, budget usage, and CodeGraph health for the current improvement session.
---

Base directory for this skill: (project root where dumbledoer is installed)

# /dumbledoer:status — Show Task Registry and Session Summary

**References** (read before Section 1): `dumbledoer/lib/common-preamble.md`

**Lazy references**: `dumbledoer/lib/memory-schema.md` (load only if the repair flow triggers), `dumbledoer/lib/archive-protocol.md` (load only for `--verbose` with archived tasks)

## Parameters

```
/dumbledoer:status
  --verbose    Optional. Show full Task Details for each task.
```

---

## Section 1 — Validate memory.md

1. Check for `memory.md`. If missing: `Error: memory.md not found. Run /dumbledoer:start to begin.` and stop.
2. Run the validation checklist from `lib/common-preamble.md`. If malformed: load `lib/memory-schema.md` and trigger the FR-016 repair flow.

---

## Section 2 — Read Data

1. Read Task Registry from `memory.md`.
2. Read Session Log from `memory.md` (last 3 entries).
3. Read Budget Tracking table from `memory.md`.
4. Run `codegraph status` to get index health, symbol count, last sync.
5. Read the knowledge registry stats: resolve `{knowledge_path}` from Config
   (default `knowledge/`); if `index.md` exists, count entries per type and status
   from it and note the most recent `created` date (index read only — do not load
   entry notes; malformed entries simply don't appear in counts). If the registry
   is absent, note that instead — do NOT create it (`lib/knowledge-protocol.md`
   invariant 3).

---

## Section 3 — Format and Output

### Status Icons

| Status | Icon |
|--------|------|
| `completed` | ✅ |
| `in_progress` | 🔄 |
| `interrupted` | ⏸ |
| `pending` | ⬜ |
| `blocked` | 🚫 |
| `deferred` | 💤 |

### Output Style

This command's output is category `simple` (`lib/compression-policy.md`): when
compression is enabled, surrounding prose is caveman `full`. The format block
below, the table structure, status icons, and all exact strings are preserved
verbatim at every level.

### Output Format

```
dumbledoer — Session {last sessionId} | Budget: {pct}% used ({tokens_estimated}/{budget_limit} est. tokens)

Project Goal: {first sentence of Project Goal from memory.md}

Task Registry:
  {icon} {taskId}  {title:<50} [{type}]  {session or —}  {note if in_progress: (step N)}

Last session: {sessionId} — {outcome} ({end time or 'active'})
CodeGraph: {✅ healthy | ⚠ stale} | {symbol_count} symbols | last sync {relative time}
Knowledge: {N} entries ({d} decisions, {s} successes, {f} failures, {c} constraints, {i} insights; {x} superseded) | last entry {date} | {knowledge_path}
```

If the registry is absent, the Knowledge line reads:
`Knowledge: no registry — /dumbledoer:start creates it`

If `--verbose`: after the Task Registry table, append the full Task Details block for each task (copy from memory.md Task Details subsections). For archived tasks (Checkpoint column = `archived`), print a one-line summary with a pointer to the archive file from the Archive Index instead — never inline archived details (`lib/archive-protocol.md`).

---

## Error Messages

| Condition | Output |
|-----------|--------|
| `memory.md` missing | `Error: memory.md not found. Run /dumbledoer:start to begin.` |
| `memory.md` malformed | FR-016 repair flow |
| CodeGraph not initialized | `CodeGraph: ⚠ not initialized — run codegraph init -i` |

