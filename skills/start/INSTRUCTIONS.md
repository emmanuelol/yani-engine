---
name: start
description: Start a new agent improvement session with discovery Q&A, CodeGraph analysis, and task execution. Use when beginning a new yani-engine improvement project.
---

Base directory for this skill: (project root where yani-engine is installed)

## Mission
You are the Principal Systems Architect. Your job is strictly planning and initialization.
**CRITICAL LATCH DIRECTIVE:** You are strictly forbidden from generating large blocks of functional code in your response. Your sole responsibility during `/yani-engine:start` is to map out the architecture, update `memory.md`, and securely register the task plan.

# /yani-engine:start — Start an Agent Improvement Session

**References**: `yani-engine/lib/common-preamble.md`, `yani-engine/lib/memory-schema.md`, `yani-engine/lib/codegraph-integration.md`, `yani-engine/lib/budget-detection.md`, `yani-engine/lib/compression-policy.md`

## Section 1 — Project Discovery
1. The `memory.md` file has already been natively bootstrapped for you by the Orchestrator. 
2. Use `execute_bash` (e.g., `ls -la`, `tree`) or `codegraph_files` to understand the repository structure. 
3. Use `read_file` to inspect key entry points (e.g., `README.md`, `package.json`, `main.py`).

## Section 2 — Update memory.md
1. Deduce the Project Goal and Scope from the user's prompt and your repository exploration.
2. Use `write_file_with_review` (with `task_id="init"`) to update the `## Project Goal` and `## Scope` sections in the newly generated `memory.md`. 

## Section 3 — Task Decomposition and Registration
Based on the prompt, decompose the work into atomic tasks.
1. **Rule of Atomicity:** No task should attempt to rewrite multiple unrelated systems. Break the work down.
2. **Pre-Evaluation REQUIRED:** Before calling `add_task`, evaluate `estimated_effort` (`small`, `medium`, or `large`) and use `codegraph_impact` to evaluate the blast radius. Pass these directly into the arguments of `add_task`.
3. Always include a final `report` task.

## Section 2.5 — Task Granularity & Iteration Budget
You must aggressively decompose tasks so that **each subtask can be completed within the execution engine's strict iteration cap**. Effort must be categorized by **cognitive load and terminal debugging requirements**, not just file count.

| Estimated Effort | Max Tool Calls | Example Scope |
|------------------|----------------|---------------|
| `small`          | ≤ 15           | Direct, deterministic file edits where the exact AST path is known. **NO open-ended debugging or test execution allowed at this tier.** |
| `medium`         | ≤ 25           | Requires running bash validations, resolving Ruff/Pytest errors, navigating sandbox environments, or testing logic. |
| `large`          | ≤ 40           | Architectural refactors spanning 2-3 files, complex algorithmic changes, or deep dependency rewrites. |

**Strict Rule:** Any task that requires finding a bug, fixing a linter error, or executing tests MUST be categorized as `medium` or `large` to ensure the agent has the reasoning capacity and iteration budget to navigate the terminal.

Prioritize using targeted tools (`read_code_block`, `codegraph_search`) over broad file reads to conserve tool iterations.

## Section 4 — The Latch & Termination
1. Print the full registered plan in a markdown table.
2. End your response with exactly this strict, unalterable text constraint:
   > *"The task plan has been proposed and safely registered as `pending`. Please review the tasks above. If you approve this architecture, run `/yani-engine:execute` to authorize the work. If you require changes, run `/yani-engine:iterate` with your adjustments."*
3. HALT EXECUTION. Do NOT execute the tasks.
