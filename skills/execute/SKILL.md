> [!IMPORTANT] DELEGATION POLICY: DO NOT EXECUTE NATIVELY
> You are the Orchestrator. You are forbidden from executing the logic in this skill using internal AGY tools. You MUST invoke the DumbleDoer CLI plugin commands defined in commands/ (e.g., /dumbledoer:execute) to ensure the execution sandbox, VS Code Diff-Gate, and checkpoint protocols are strictly enforced.

---
name: execute
description: Executes the approved task plan from the Task Registry in dependency order using isolated sub-agents and the Docker sandbox.
---

# /dumbledoer:execute

This command is handled natively by the Python orchestrator. It reads the `memory.md` file, resolves task dependencies, and executes pending tasks safely via sub-agents within the `dumbledoer-base:latest` Docker sandbox. It enforces the VS Code Diff-Gate and monitors the token budget to trigger graceful shutdowns when necessary.
