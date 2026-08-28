# context7-protocol: Current Documentation Lookup for External Dependencies

Single authoritative statement of when and how yani-engine consults current library
documentation. Applied via the reference in `lib/common-preamble.md`. Command
files MUST NOT restate these rules.

The lookup uses the **Context7** MCP server, bundled with the plugin via
`yani-engine/.mcp.json` (`npx -y @upstash/context7-mcp`). The protocol references the
tools by capability — a "resolve library id" tool and a "query docs" tool — so a
globally-configured Context7 instance (whatever its tool prefix) satisfies it
equally.

---

## When a Lookup Is Required

A task REQUIRES a documentation lookup when its change or analysis depends on the
API of an external library, framework, SDK, or CLI tool — anything whose behavior
is versioned outside the project (e.g., a prompt that embeds SDK call syntax, a
config for a framework, tool definitions matching a vendor API).

A task is EXEMPT (no lookup, zero added latency, no record written) when it
touches only project-local prompts, docs, and files with no external API surface.

### Tagging and re-check

- **Decomposition time** (start Section 7): each registered task notes whether it
  involves external dependencies (name the libraries when known).
- **Execution time**: the executing agent re-checks before the FIRST dependent
  change — a mis-tagged task is corrected then (lookup performed if a dependency
  emerges; skipped if none actually exists).

---

## Lookup Operation

BEFORE proposing or executing the dependent change:

1. Call the resolve-library-id tool with the library name.
2. Call the query-docs tool with the resolved ID and a task-specific question
   (what you are about to change, version-sensitive details first).
3. Base the change on the returned documentation — current docs override
   built-in knowledge on API syntax, parameters, and defaults.
4. Append to the task's Notes field in memory.md:
   `Docs consulted: {library} ({resolved_id}) — found.`

### Outcomes

| Outcome | Meaning | Record in task Notes | User-facing |
|---|---|---|---|
| `found` | Docs retrieved; change based on them | `Docs consulted: {library} ({resolved_id}) — found.` | nothing extra |
| `not-found` | No library match | `Docs lookup: {library} — not-found.` | disclosure line |
| `unavailable` | Server unreachable or cap exceeded | `Docs lookup: {library} — unavailable.` | disclosure line |
| `skipped` | No external dependency | nothing | nothing |

### Cap and fallback

- Cap: **2 attempts, ~10 seconds total** per library. Never let a slow or
  rate-limited lookup block the task beyond the cap.
- On `not-found` or `unavailable`: proceed using built-in knowledge and include
  in the task's user-facing output exactly:

```
Note: current documentation for '{library}' could not be retrieved — proceeding on built-in knowledge.
```

This disclosure line is an exact-output string (`lib/compression-policy.md`):
compression never rewords it.

---

## Interaction with Other Protocols

- The lookup happens BEFORE the codegraph 10-step change flow writes anything —
  see the doc-lookup step in `lib/codegraph-integration.md`.
- Sub-agents inherit this protocol via the Sub-Agent Instruction Template
  (start Section 8) when their task is tagged with external dependencies.
- Lookup results are conversational context plus a Notes line — they are never
  written into persisted artifacts verbatim unless the change itself requires it.

