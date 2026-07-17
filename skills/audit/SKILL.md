---
description: QA Harness Loop. Evaluates completed tasks against their success criteria and autonomously generates fix tasks if bugs are found.
---

Base directory for this skill: (project root where dumbledoer is installed)

# /dumbledoer:audit — Autonomous Self-Evaluation Loop

**References** (read before Section 1): `dumbledoer/lib/common-preamble.md`, `dumbledoer/lib/memory-schema.md`

## Mission
You are acting as the QA Supervisor. Your job is to evaluate the tasks recently marked as `completed` in the current session. You must aggressively attempt to break the newly implemented features, verify they meet their `Success Criteria`, and autonomously generate new tasks if you find regressions or missing logic.

---

## Section 1 — Context Retrieval
1. Read `memory.md`. Identify all tasks with the status `completed` that were executed in the most recent session.
2. Read the `Success Criteria` and `Outputs` (affected files) for each of these tasks.

## Section 2 — Execution Sandbox Validation
For each completed task:
1. Formulate a test strategy.
2. Use the `execute_bash` tool to actively test the code within the Docker sandbox. Run syntax checkers (e.g., `python -m py_compile`, `uv run pytest`), type checkers, or execute the target scripts to verify they do not throw errors.
3. Use `codegraph_affected` to check if downstream dependencies were broken by the changes.

## Section 3 — The Harness Loop (Task Generation)
1. Evaluate the output from your bash tests against the `Success Criteria`.
2. **If the test passes:** Do nothing for that task. 
3. **If the test fails or criteria are unmet:** You MUST use the `add_task` tool to append a new fix task to the `memory.md` Task Registry. 
   - Set the Task Type to `change`.
   - Set the title to clearly state the bug found (e.g., "Fix Type Error in Reporting Pipeline").
   - Set the `Depends On` field appropriately.

## Section 4 — Audit Report
Once all completed tasks are evaluated, output a concise audit report detailing what was tested, what passed, and what new tasks (if any) were autonomously added to the queue for the next Execution Wave.