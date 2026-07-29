# Use Guide

DumbleDoer operates dynamically. Whenever you invoke the `dumbledoer` command, it targets the **current working directory**. Because DumbleDoer runs its core runtime from its central installation, your target repository remains clean. Only `memory.md` and `.dumbledoer/` rollback directories are created inside your active project.

## CLI Commands and Flags

DumbleDoer commands accept several granular flags to control behavior:

- `dumbledoer start`: Ingests documentation and registers an atomic task plan for the current project.
  - `--docs <path>`: (Default: `./docs`) Explicitly point DumbleDoer to a documentation directory for discovery.
- `dumbledoer execute`: Runs the registered tasks in dependency order.
  - `--dry-run`: (Type: `bool`, Default: `false`) Execute tasks but don't apply changes to disk, useful for validating task dependencies.
  - `-v`: (Type: `bool`, Default: `false`) Verbose mode; enables the manual Diff-Gate review process via VS Code.
- `dumbledoer iterate`: Evaluates a user prompt against the current project state and decomposes it into atomic tasks.
  - `--enrich`: (Type: `bool`, Default: `false`) Automatically pulls extra context from Context7 before planning.
- `dumbledoer audit`: Runs the QA Harness Loop against completed tasks to autonomously generate fixes.
  - `--budget-threshold <pct>`: (Type: `integer`, Default: `80`) Specify the threshold percentage for token budget exhaustion before triggering a graceful shutdown.
- `dumbledoer resume`: Detects stale locks and offers options to resume, rollback, or skip.
- `dumbledoer report`: Generates an improvement report using CodeGraph metrics.

## `memory.md` Configuration and Tracking

The `memory.md` file acts as the state machine and working memory for the DumbleDoer session. It tracks configuration, task registries, and logs.

### Configuration Fields (Config block)
- **`budget_limit`**: (Type: `integer`, Default: `100000`) The absolute token limit for the session.
- **`budget_threshold_pct`**: (Type: `integer`, Default: `80`) The percentage of `budget_limit` at which DumbleDoer will perform a graceful shutdown.
- **`sandbox_mode`**: (Type: `string`, Default: `dumbledoer-base`) The execution environment. Can be `native`, `docker:<image>`, or `compose:<service>`.
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
