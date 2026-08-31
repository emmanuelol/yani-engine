# ADR-001: Markdown AST DOM (`memory.md`) Over Embedded SQLite for Agent State

## Status
**Accepted**

## Date
2026-08-30

## Context
Autonomous agent orchestration requires maintaining state across tasks, waves, and sessions. Common options for state tracking include:
1. **Relational Database (SQLite/DuckDB)**: Fast structured queries, transaction isolation, binary format.
2. **Key-Value / Document Store (JSON/YAML)**: Lightweight, text-based, prone to race conditions and schema drift during multi-agent mutations.
3. **Structured Markdown Document (`memory.md`) with AST DOM Parser**: Human-readable, Git-native diffs, zero runtime binary dependency, manipulated via Abstract Syntax Tree (`markdown-it-py`).

Early architectural discussions considered migrating `memory.md` to an embedded SQLite database to handle higher task concurrency.

## Decision
We deliberately retain **`memory.md`** as the single source of truth for agent state and task registries, backed by:
1. **AST-Driven DOM Manipulation (`markdown-it-py`)**: Eliminates regex string-clobbering and markdown table serialization corruption (`format_markdown_row` & `split_markdown_cells`).
2. **MultiLoopAsyncLock & ThreadPool File Mutex**: In-memory caching (`_TASK_CACHE`) with background thread-pool locks (`asyncio.to_thread(_FILE_LOCK)`) ensuring atomic `os.replace` flushes.
3. **Pydantic Tool Bouncers**: Strict runtime schema validation (`UpdateTaskStatusPayload`, `TaskBatchPayload`) before mutating memory state.

## Rationale & Tradeoffs

### Advantages
* **Human Auditing & Git-Native History**: Every state change, task registration, and wave outcome is committed as plain Markdown. Reviewers and CI audit logs can inspect `git diff memory.md` without SQLite CLI or external tooling.
* **Zero-Friction Local-First Integration**: Developers can inspect, edit, or recover agent state directly inside their editor.
* **Seamless Context Injection**: Markdown blocks from `memory.md` can be sliced and directly injected into LLM prompt envelopes without serialization overhead.
* **Deterministic Rollbacks**: Checkpoint snapshots (`.yani/checkpoints/`) map 1:1 to plain markdown files.

### Mitigations for Markdown Limitations
* *Concurreny*: Handled by `MultiLoopAsyncLock` in RAM, flushing atomically via `ThreadPoolExecutor` file locks.
* *Token Inflation*: Sliced memory ingestion ensures only targeted sections of `memory.md` reach LLM context.
* *Corruption*: Pydantic schema validation rejects malformed rows before lock acquisition.

## Future Scaling Path
When scaling to distributed multi-node agents across remote clusters, a dual-layer strategy will be adopted (see `ROADMAP.md`): local execution retains `memory.md` for human review, while distributed telemetry exports state snapshots via OpenTelemetry OTLP collectors.
