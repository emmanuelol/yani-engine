---
name: iterate
description: Iterates on the current dumbledoer session by adding new tasks to the registry based on a user prompt.
---

Base directory for this skill: (project root where dumbledoer is installed)

# /dumbledoer:iterate — Refine the Task Plan

**References** (read before Section 1): `dumbledoer/lib/common-preamble.md`, `dumbledoer/lib/memory-schema.md`, `dumbledoer/lib/codegraph-integration.md`

## Mission
The user has provided a new objective to add to the current, active DumbleDoer session. You must analyze the request, identify necessary changes to the repository, and autonomously append the required tasks to the `memory.md` Task Registry.

---

## Section 1 — Pre-flight Validation
1. Verify `memory.md` exists. If missing, abort and instruct the user to run `/dumbledoer:start`.
2. Review the user's newly provided objective.
3. Utilize `codegraph_search` and `codegraph_impact` to understand how the new objective fits into the existing codebase and currently planned tasks.

## Section 2 — Task Formulation
1. Decompose the user's objective into atomic tasks (`change`, `analysis`, `validation`).
2. Identify dependencies. Does the new task depend on a `pending` task already in the registry?
3. **Mandatory Execution:** Use the `add_task` tool to append each new task to the registry safely. Do not attempt to rewrite the entire `memory.md` file manually.
4. If a task requires external library integration, follow the documentation lookup rules in `dumbledoer/lib/context7-protocol.md`.

## Section 3 — Confirmation
Once the tasks are successfully added to the registry via the `add_task` tool, output a brief summary confirming the new tasks and instruct the user to run `/dumbledoer:execute` to begin the parallel execution waves.
