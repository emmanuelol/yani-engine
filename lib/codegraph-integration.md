# codegraph-integration: Mandatory CodeGraph Usage Rules for Sub-Agents

Every sub-agent spawned by dumbledoer MUST follow these rules. No code change or
file modification may proceed without first querying CodeGraph.

---

## Prerequisite: CodeGraph Must Be Initialized

Before any sub-agent begins work, verify `.codegraph/` exists in the project root.

If `.codegraph/` is absent:
- Run `codegraph init -i` (or alert the parent session to do so).
- Do not modify any files until the index is built.

---

## Available MCP Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `codegraph_search` | Find symbols by name across the codebase | First step when locating a target function, class, or file |
| `codegraph_context` | Build relevant code context for a task | During `analysis` tasks to understand a component's role |
| `codegraph_impact` | Analyze what code is affected by changing a symbol | **MANDATORY** before any file write in a `change` task |
| `codegraph_callers` | Find what calls a function | Understanding dependencies before refactoring |
| `codegraph_callees` | Find what a function calls | Understanding a function's reach before changing it |
| `codegraph_node` | Get details about a specific symbol | Inspecting a single symbol's definition and source |
| `codegraph_files` | Get indexed file structure | Faster than filesystem scanning for project layout |
| `codegraph_status` | Check index health and statistics | Session start baseline + report generation |
| `codegraph_affected` | Find test files affected by changed source files | After every file write to identify tests to run |

---

## 10-Step Data Flow for Change Tasks

Every `change` task sub-agent MUST execute these steps in order.

**Step 0 — documentation lookup (when tagged)**: if the task involves an external
library, framework, SDK, or CLI tool API, run the lookup operation from
`lib/context7-protocol.md` BEFORE step 1 — current docs must inform the change
before any analysis is logged or any file is written. Tasks with no external
dependency skip this step entirely (zero added latency).

```
1. codegraph_search("{target symbol or filename}")
   → Locate the exact symbol or file to modify
   → Confirm it is the intended target (not a similarly-named symbol)

2. codegraph_impact("{symbol}", depth=3)
   → Blast-radius analysis: what calls this, what this calls, what imports it
   → HALT if impact radius is unexpectedly large (>20 symbols): alert parent session
     and request task split or explicit user confirmation before proceeding

3. Log impact summary to memory.md Task Details, CodeGraph Impact field:
   "Affects N symbols across M files: [symbol1 (file.md), ...]"
   → This is required BEFORE writing any rollback copy or checkpoint

4. codegraph_callers("{symbol}")
   → Understand all upstream dependencies that will be affected

5. Copy original file to rollbacks/{taskId}/  [Step 1 of checkpoint-protocol.md]

6. Write planned entry to Change Log          [Step 2 of checkpoint-protocol.md]

7. Write checkpoint JSON                      [Step 3 of checkpoint-protocol.md]

8. Write new content to tmp/{file}.tmp        [Step 4 of checkpoint-protocol.md]

9. Rename tmp → target path                   [Step 5 of checkpoint-protocol.md]

10. codegraph_affected([modified files])
    → Identify test files that must be re-run after the change
    → Log affected test files in task Notes field
    → Update Change Log entry to applied     [Step 6 of checkpoint-protocol.md]
```

---

## Impact Radius Thresholds

| Impact Radius | Action |
|---------------|--------|
| 0–5 symbols | Proceed normally |
| 6–20 symbols | Note all affected symbols in CodeGraph Impact field; proceed |
| 21+ symbols | HALT; alert parent session; request task split or explicit confirmation |
| Cross-component impact | Note boundary being crossed; proceed only after confirmation |

---

## Rules for Analysis Tasks (type: analysis)

`analysis` tasks do NOT modify files. They MUST:
1. Use `codegraph_context` and `codegraph_search` instead of grep/glob/Read for exploration.
2. Use `codegraph_node` to inspect specific symbols.
3. Write findings to memory.md task Notes field.
4. NOT call `codegraph_impact` unless specifically analyzing impact for a planned future change.

---

## Rules for Sub-Agent File Ownership

Before a sub-agent begins work on any file, it MUST:
1. Read the Task Registry in `memory.md`.
2. Check if any other task has status `in_progress` and lists that file in its Outputs.
3. If yes: HALT. Do not modify the file. Alert parent session — file is owned by another
   in-progress task.
4. If no: proceed.

A sub-agent MUST NOT modify any file outside its task's declared `Outputs` list.

---

## Logging Requirements

After every `codegraph_impact` call, the sub-agent MUST log in the task's CodeGraph
Impact field in memory.md:

```
[{timestamp}] codegraph_impact("{symbol}"): {N} symbols affected across {M} files.
Affected: {symbol1} ({file1.ext}), {symbol2} ({file2.ext}), ...
Test files to run: {test1.ext}, {test2.ext}
```

This log is used by `/dumbledoer report` to generate quantitative justification
for each change.

---

## CodeGraph Auto-Sync

CodeGraph auto-syncs on file save (2-second debounce). After any batch of file changes:
1. Wait ~3 seconds for auto-sync to complete.
2. Run `codegraph status` to confirm index is fresh.
3. If `codegraph status` shows stale index: run `codegraph sync` manually.

After rollback operations, always run `codegraph sync` explicitly to rebuild from
the restored file state.

