# Use Guide

DumbleDoer operates dynamically. Whenever you invoke the `dumbledoer` command, it targets the **current working directory**.

## Basic Commands

- `dumbledoer start --docs ./docs`: Ingests documentation and registers an atomic task plan for the current project.
- `dumbledoer execute --focus system`: Runs the registered tasks in dependency order.
- `dumbledoer resume`: Detects stale locks and offers options to resume, rollback, or skip.
- `dumbledoer report`: Generates an improvement report using CodeGraph metrics for the active directory.

## Zero-Copy Semantic Audits

Because DumbleDoer runs its core runtime from its central installation, your target repository remains clean. Only `memory.md` and `.dumbledoer/` rollback directories are created inside your active project.
