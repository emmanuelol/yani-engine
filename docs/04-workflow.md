# Session Workflow

yani-engine operates via a structured, heavily guarded workflow ensuring safe execution, clear state tracking, and token efficiency.

## 1. Initialization
Navigate to the project you wish to improve and run `/yani-engine start`. yani-engine maps its CodeGraph context and `memory.md` tracking directly to this active directory.

## 2. Planning (10-Step CodeGraph Impact Analysis)
During the planning phase, changes undergo a rigorous 10-step CodeGraph Impact Analysis Data Flow:
1. **Identify Target Symbol**: Sub-agent flags the function or class to be modified.
2. **CodeGraph Node Query**: Fetches exact AST bounds of the symbol.
3. **Reference Search**: CodeGraph searches the workspace for direct invocations.
4. **Call Graph Construction**: Builds a tree of downstream dependents.
5. **Impact Radius Calculation**: Counts total affected symbols across the dependency chain.
6. **Threshold Enforcement**: Rejects structural changes if the radius exceeds 20 symbols.
7. **Cross-File Lock Check**: Verifies none of the affected files are locked by concurrent tasks.
8. **Dependency Injection**: Sub-agent explicitly injects required contextual files.
9. **Execution Approval**: Approves the modification scope for the execution wave.
10. **State Registration**: Logs the blast radius data into the Task Registry field.

## 3. Execution (6-Step Checkpoint & Rollback Protocol)
When running `/yani-engine execute`, the central yani-engine logic executes tasks using its isolated `.venv`. Each file modification strictly adheres to the 6-Step Checkpoint & Rollback Protocol:
1. **Pre-Write Snapshot**: `CheckpointManager` logs the current state of the file before any modification.
2. **Rollback Backup Generation**: A `.bak` file is safely stored in `.yani/rollbacks/{task_id}/`.
3. **Registry Update**: A `planned` entry is created in the `Change Log` of `memory.md`.
4. **Shadow File Creation**: The new code is written to a `.tmp` file for Diff-Gate review.
5. **Diff-Gate Review**: VS Code (or Terminal) presents the diff against the rollback backup.
6. **Commit or Revert**: If approved, `.tmp` overwrites the target; if rejected, the `.bak` file is restored to clear out any intermediate artifacts.

## 4. Communication & Optimization
### Caveman Integration (Dynamic Output Compression)
To maximize token savings during execution, yani-engine leverages the **Caveman** skill. This enforces an ultra-compressed communication mode, aggressively filtering out pleasantries and redundant markdown formatting from the LLM’s output. It operates at multiple intensity levels to cut token usage by up to 75% while retaining full technical accuracy during heavy multi-turn loops.

### Knowledge Registry Vault Operations
At the completion of complex tasks, yani-engine logs durable learnings to the Knowledge Vault (`knowledge/`):
- Records critical insights, architectural constraints, and failure modes.
- Saves findings in structured markdown entries (`knowledge/entries/`).
- Synchronizes with `knowledge/index.md` via `sync_knowledge.py` (OP-9 protocol) for automatic re-ingestion in future sessions, enabling bridging of decisions across multiple project instances.

## 5. Completion
yani-engine generates the `/report` locally and synchronizes `memory.md`. Your project is updated, while yani-engine safely returns to idle in its centralized location.
