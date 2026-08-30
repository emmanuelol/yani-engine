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
7. **Fail-Closed Timeout Protection**: If CodeGraph analysis exceeds 5 seconds, the modification is immediately blocked to prevent unmonitored blast-radius creep.
8. **Cross-File Lock Check**: Verifies none of the affected files are locked by concurrent tasks.
9. **Execution Approval**: Approves the modification scope for the execution wave.
10. **State Registration**: Logs the blast radius data into the Task Registry field.

## 3. Execution (Zero-Copy Worktree Sandbox & Checkpoint Protocol)
When running `/yani-engine execute`, tasks are dynamically scheduled into parallel waves. Each worker executes in an isolated environment under strict guardrails:
1. **Ephemeral Git Worktree Allocation**: Workers requiring bash or test execution instantiate a zero-copy Git Worktree at `.yani/shadow_{worker_id}` linked to an isolated Docker container (`yani-base:latest`), bypassing slow directory cloning.
2. **Pydantic Validation Gate**: State mutations (`update_task_registry_row`, `register_task_batch`) validate payloads against Pydantic models before acquiring mutexes, returning character-capped error traces ($\le 1600$ chars) on schema errors to prevent token bleed.
3. **Pre-Write Snapshot & Rollback**: Before modifying target files, `CheckpointManager` backs up originals to `.yani/rollbacks/{task_id}/{encoded_path}` and logs a `planned` entry in `memory.md`.
4. **Shadow Staging**: Modified code is staged to `.yani/tmp/{task_id}_{encoded_path}.tmp`.
5. **Diff-Gate Review**: Interactive modal compares staged `.tmp` against rollback backup in VS Code or rich terminal diff.
6. **Commit or Revert**: Upon approval, staged files atomically overwrite targets; upon rejection, rollback copies restore the clean tree.

## 4. `yani-skill` Deterministic Workflow (Alternative Strict Path)
When invoking `/yani-skill` (or `/yani-engine:yani-skill`), the execution follows an evidence-based, four-phase lifecycle:
1. **Recon & Convention Mining**: Executes `cochange.py` on target files to compute historical commit coupling and verify reproducibility via `verify_evidence.py`. High ratios establish hard `convention_guards`.
2. **Atomic Planning**: Generates `plan.json` and runs `validate_plan.py` to ensure schema validity and non-overlapping `files_touched`. Pauses for explicit human confirmation.
3. **Test-Driven Execution (TDA)**: Creates an isolated temporal branch (`yani/T-XX`), writes failing tests first, and implements changes.
4. **Deterministic Audit**: Executes `diff_audit.py` comparing the working tree to the base branch and asserting all `--expect` convention guards were satisfied before prompting for human commit authorization.

## 5. Communication & Optimization
### Caveman Integration & Token Bleed Envelope
To maximize token savings during execution, yani-engine leverages **Caveman Mode** for ultra-compressed communication (cutting prompt tokens by up to 75%). When tool parameter errors occur, validation messages are bounded by `_format_validation_error` to protect prompt history from hallucinated input overflow.

### Knowledge Registry Vault Operations
At the completion of complex tasks, yani-engine logs durable learnings to the Knowledge Vault (`knowledge/`):
- Records critical insights, architectural constraints, and failure modes.
- Saves findings in structured markdown entries (`knowledge/entries/`).
- Synchronizes with `knowledge/index.md` via `sync_knowledge.py` (OP-9 protocol) for automatic re-ingestion in future sessions, enabling bridging of decisions across multiple project instances.

## 6. Completion
yani-engine generates the `/report` locally and synchronizes `memory.md`. Your project is updated, while yani-engine safely returns to idle in its centralized location.
