---
name: execute
description: Executes the approved task plan from the Task Registry in dependency order using isolated sub-agents and the Docker sandbox.
---

# /dumbledoer:execute

This command is handled natively by the Python orchestrator. It reads the `memory.md` file, resolves task dependencies, and executes pending tasks safely via sub-agents within the `dumbledoer-base:latest` Docker sandbox. It enforces the VS Code Diff-Gate and monitors the token budget to trigger graceful shutdowns when necessary.
