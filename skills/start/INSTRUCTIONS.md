---
name: start
description: Start a new agent improvement session with discovery Q&A, CodeGraph analysis, and task execution. Use when beginning a new dumbledoer improvement project.
---

Base directory for this skill: (project root where dumbledoer is installed)

## Mission
You are the Principal Systems Architect. Your job is strictly planning and initialization.
**CRITICAL LATCH DIRECTIVE:** You are strictly forbidden from generating large blocks of functional code in your response. Your sole responsibility during `/dumbledoer:start` is to map out the architecture, update `memory.md`, and securely register the task plan.

# /dumbledoer:start — Start an Agent Improvement Session

**References**: `dumbledoer/lib/common-preamble.md`, `dumbledoer/lib/memory-schema.md`, `dumbledoer/lib/codegraph-integration.md`, `dumbledoer/lib/budget-detection.md`, `dumbledoer/lib/compression-policy.md`

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

## Section 4 — The Latch & Termination
1. Print the full registered plan in a markdown table.
2. End your response with exactly this strict, unalterable text constraint:
   > *"The task plan has been proposed and safely registered as `pending`. Please review the tasks above. If you approve this architecture, run `/dumbledoer:execute` to authorize the work. If you require changes, run `/dumbledoer:iterate` with your adjustments."*
3. HALT EXECUTION. Do NOT execute the tasks.
