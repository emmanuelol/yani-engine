# Agent Commands & Workflow Triggers

The following system commands dictate the primary workflow logic handled by the orchestrator (`dumbledoer_cli.py`).

## `/start`
- **Action**: Initializes a new session.
- **Workflow**:
  1. Ingests all project documentation.
  2. Conducts a Discovery Q&A with the user (or reads existing specs).
  3. Performs edge-case detection to identify potential pitfalls early.
  4. Registers an atomic task plan in the `memory.md` Task Registry.

## `/execute`
- **Action**: Processes the Task Registry.
- **Workflow**:
  1. Executes the registered tasks in dependency order.
  2. Utilizes concurrent Gemini sub-agent calls wherever there are no overlapping output files.

## `/resume`
- **Action**: Recovers from an interrupted or paused state.
- **Workflow**:
  1. Detects interrupted tasks or stale file locks.
  2. Offers options to the user to resume from a checkpoint, roll back, or defer.

## `/rollback`
- **Action**: Reverts the project state.
- **Workflow**:
  1. Restores files from the `.dumbledoer/rollbacks/` directory based on Checkpoint Registry.
  2. Resets the reverted task status back to "Pending" in the Task Registry.

## `/report`
- **Action**: Analyzes and outputs project deltas.
- **Workflow**:
  1. Generates a quantitative before/after improvement report.
  2. Details the CodeGraph impact radius for transparency.
  3. Provides comprehensive delta summaries.

## `/update-docs`
- **Action**: Synchronizes system documentation.
- **Workflow**:
  1. Syncs project documentation with the current codebase using CodeGraph structural analysis to identify undocumented new symbols.
