# Use Guide

yani-engine operates dynamically. Whenever you invoke the `yani-engine` command, it targets the **current working directory**. Because yani-engine runs its core runtime from its central installation, your target repository remains clean. Only `memory.md` and `.yani/` rollback directories are created inside your active project.

## CLI Commands and Flags

### Global Execution Flags
- `--trace`: (Type: `bool`, Default: `false`) Enable OpenTelemetry distributed tracing and metrics recording.
- `--otlp-endpoint <url>`: (Default: `None`) Export telemetry traces directly to an OpenTelemetry collector over HTTP/Protobuf.
- `--log-format <console|json>`: (Default: `console`) Select structlog output format.
- `--model <name>`: Override default model tier for the run.
- `-v`, `--verbose`: Enable detailed verbose logging and interactive Diff-Gate modals.

### Command Reference
- `yani-engine start`: Ingests documentation and registers an atomic task plan for the current project.
  - `--docs <path>`: (Default: `./docs`) Explicitly point yani-engine to a documentation directory for discovery.
- `yani-engine execute`: Runs registered tasks in parallel waves matching dependency constraints.
  - `--dry-run`: (Type: `bool`, Default: `false`) Execute task planner without modifying working tree.
  - `-v`: (Type: `bool`, Default: `false`) Verbose mode with interactive Diff-Gate review.
- `yani-engine iterate`: Evaluates a prompt against project memory and generates bounded task batches.
  - `--enrich`: (Type: `bool`, Default: `false`) Automatically queries Context7 semantic docs before planning.
- `yani-engine audit`: Runs the QA Harness Loop against completed tasks to autonomously generate fixes.
  - `--budget-threshold <pct>`: (Type: `integer`, Default: `80`) Specify token exhaustion threshold percentage.
- `yani-engine resume`: Detects stale locks / interrupted tasks with options to Resume (`R`), Rollback (`B`), or Skip (`S`).
- `yani-engine rollback`: Safely restores files from `.yani/rollbacks/` checkpoints.
  - `<task_id>`: Restore a specific task (e.g. `T-001`).
  - `--all`: Roll back all modified files across the current session.
- `yani-engine update-docs`: Inspects git changes and CodeGraph AST symbols to register documentation update tasks.
  - `--docs <path>`: Target documentation path (default `./docs`).
- `yani-engine report`: Generates an improvement report using CodeGraph AST metrics.
- `yani-engine status`: Displays live Task Registry status and MCP server health.
- `yani-engine:yani-skill` (or `/yani-skill`): **Lite Fast-Path Mode** — Lightweight, deterministic planner & auditor for daily pairing without Docker setup.

---

## 🧑‍🏫 Tutorial: Choosing the Right Tool for the Job

yani-engine adapts to the complexity of your task. Here is how to decide which execution path to take:

**Scenario A: "I need to fix a quick UI bug in my React component."**
Use **Lite Mode**. Run `/yani-skill` in your terminal. It skips the Docker sandbox and immediately calculates the historical Git co-change ratio for your target file. It writes a failing test, implements the fix, and runs a strict diff-audit against your base branch before pausing for your approval.

**Scenario B: "I need to migrate my entire backend from Flask to FastAPI."**
Use the **Full Harness**. Run `/yani-engine start`. This requires structural blast-radius protection. The engine will query the CodeGraph AST to ensure no single refactor wave breaks more than 20 upstream symbols. It will execute the migration asynchronously across multiple sub-agents, utilizing `memory.md` to track persistent state and checkpoint backups.

---

## `memory.md` Configuration and Tracking

The `memory.md` file acts as the state machine and working memory for the yani-engine session. It tracks configuration, task registries, and logs.

### Configuration Fields (Config block)
- **`budget_limit`**: (Type: `integer`, Default: `100000`) The absolute token limit for the session.
- **`budget_threshold_pct`**: (Type: `integer`, Default: `80`) The percentage of `budget_limit` at which yani-engine will perform a graceful shutdown.
- **`sandbox_mode`**: (Type: `string`, Default: `yani-base`) The execution environment. Can be `native`, `docker:<image>`, or `compose:<service>`.
- **`max_parallel_tasks`**: (Type: `integer`, Default: `0` [unlimited]) Maximum concurrent tasks to execute in a parallel wave.
- **`archive_keep_sessions`**: (Type: `integer`, Default: `1`) Number of historical sessions to retain in the Session Log.

### Task Registry Fields
- **Task ID**: Unique identifier (e.g., `T-001`).
- **Title**: Brief description of the task.
- **Type**: (e.g., `change`, `investigate`).
- **Status**: Current state (`pending`, `in_progress`, `completed`, `awaiting-review`, `error`, `deferred`, `abandoned`).
- **Owner**: Assigned sub-agent or `—`.
- **Depends On**: Comma-separated list of Task IDs that must complete first.
- **Assigned Session**: The session ID currently executing the task.
- **Outputs**: List of files created or modified by the task.

### Checkpoint Registry
Records the exact state of files before modification, linking `Checkpoint ID` to `Task ID`, `Step`, and `Files Snapshotted` for reliable rollback.
