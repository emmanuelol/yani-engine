# compression-policy: Dynamic Output Compression (caveman)

Single authoritative statement of how dumbledoer compresses conversational
output. Every command applies this policy via the reference in
`lib/common-preamble.md`. Command files MUST NOT restate these rules.

Compression uses the **caveman** ruleset, which ships WITH the plugin at
`dumbledoer/skills/caveman/SKILL.md` (vendored from github.com/JuliusBrussee/caveman,
MIT) — nothing to install. That file defines HOW each level reads (rules,
intensity table, auto-clarity exceptions); this policy defines WHEN it applies
and at WHICH level. DumbleDoer auto-applies only `lite` (drop filler, keep all
nuance) and `full` (default caveman terseness); `ultra` and `wenyan` are NEVER
applied automatically — the user may request them manually.

---

## Session State

- The on/off switch is `compression_enabled` in memory.md Config.
  - `true` → policy active. `false` → all output is normal prose.
  - **Absent field ⇒ `true`** (default-on; backward compatible with older memory.md files).
  - Invalid value → non-fatal: report the offending value and ask the user to pick
    `true` or `false`; never halt the session over this field.
- The active LEVEL is never stored — it is recomputed per response from the
  category mapping below.

### No installation, no detection

The caveman ruleset is bundled with the plugin (`skills/caveman/SKILL.md`), so
there is NO availability check and NO degraded mode: when `compression_enabled`
is `true`, the policy applies; when `false`, output is normal prose. The bundled
skill's auto-clarity exceptions (security warnings, irreversible-action
confirmations, sequences where compression risks misreading) apply at every
level and may locally suspend compression without changing session state.

---

## Category → Level / Model-Tier Mapping

| Category | Compression level | Sub-agent model tier |
|---|---|---|
| `simple` | caveman `full` | standard — request `gemini-3.5-flash` at spawn |
| `complex` | caveman `lite` | premium — request `gemini-3.1-pro-preview` at spawn |
| `planning` / persisted artifacts | off (normal prose) | main session model (premium where spawned) |

### Classification rules

1. **Command identity**: `/dumbledoer:status` and `/dumbledoer:rollback`
   output → `simple`. Report and update-docs COMPOSITION dialogue → `planning`.
2. **Task metadata** (from Task Registry): type `change` OR effort
   `medium`/`large` → `complex`. Type `analysis`/`validation` AND effort `small`
   → `simple`. Failure diagnosis discussion → `complex`.
3. **Planning phases**: start Sections 4–7 (ingest, discovery Q&A, task
   decomposition, plan confirmation) and resume interrupted-task review /
   session menu → `planning`.
4. **Artifact override** (absolute): ANY content written to disk — reports,
   memory.md prose fields, knowledge entries, timeline sections, handoff
   summaries, docs, checkpoints — is normal full prose, regardless of category
   or compression state.
5. **Mixed responses**: a single response spanning categories uses the LIGHTEST
   involved compression (`complex`+`simple` → `lite`; anything+`planning` →
   uncompressed).

### Model-tier fallback

When the requested tier is unavailable (pinned model policy, quota, outage),
spawn on the session default model and output once per session:

```
Note: preferred model tier unavailable — continuing on the session default model.
```

---

## Invariants (apply at every level)

- **Byte-preservation**: code blocks, file paths, identifiers, commands, URLs,
  and numeric values are reproduced exactly — never compressed, paraphrased, or
  abbreviated.
- **Structure preservation**: tables, checklists, and fenced output blocks keep
  their structure; only surrounding prose compresses.
- **Exact-output strings**: any text a contract defines verbatim (error messages,
  summary blocks, scan reports, the notices in this file) is NEVER reworded.
- **Accuracy over brevity**: if compressing would drop information the user needs
  to act, keep the information and drop the compression instead.

---

## Mid-Session Toggle

- User says `normal mode` → set `compression_enabled: false` in memory.md Config
  in the same turn; normal prose from the next response onward.
- User says `caveman mode` → set `compression_enabled: true` in the same turn;
  policy active from the next response onward.
- The in-flight response may complete in the old style; everything after follows
  the new state. Acknowledge a toggle with one line, e.g.
  `Output compression disabled for this session.` /
  `Output compression enabled for this session.`
- Because the Config write happens in the same turn, a later resume restores the
  toggled state (FR-011).

---

## Sub-Agent Directives

When start/resume Section 8 spawns a sub-agent, the spawn MUST:

1. Classify the task per the rules above.
2. Request the mapped model tier (`gemini-3.5-flash` for `simple`, `gemini-3.1-pro-preview` for `complex`).
3. Include in the sub-agent prompt: the task's compression level (`full`, `lite`,
   or `off`) and the byte-preservation + artifact-override invariants.

Sub-agents apply the level to their conversational replies only; all their file
writes follow the artifact override.

