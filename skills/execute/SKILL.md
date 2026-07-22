> [!IMPORTANT] EXECUTION DIRECTIVE: When the user invokes this command, you MUST immediately execute the corresponding JSON tool defined in the commands/ directory. Do not explain the command to the user. Do not ask the user to run it in their terminal. Execute the tool call silently and report the output.

---
name: execute
description: Executes the approved task plan from the Task Registry in dependency order using isolated sub-agents and the Docker sandbox.
---

# /dumbledoer:execute

This command is handled natively by the Python orchestrator. It reads the `memory.md` file, resolves task dependencies, and executes pending tasks safely via sub-agents within the `dumbledoer-base:latest` Docker sandbox. It enforces the VS Code Diff-Gate and monitors the token budget to trigger graceful shutdowns when necessary.
