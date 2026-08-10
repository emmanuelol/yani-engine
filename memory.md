# Memory

## Config
- budget_limit: 15000000
- budget_threshold_pct: 80
- session_count: 1
- codegraph_baseline_symbols: 0
- codegraph_baseline_sync: 1970-01-01T00:00:00Z
- codegraph_backend: native
- sandbox_mode: dumbledoer-base

## Project Goal
Perform a ruthless, adversarial audit of the execution pipeline to identify systemic failure vectors such as asyncio deadlocks, split-brain sandbox issues, token bleeds, and exception swallowing.

## Scope
- `dumbledoer/core/orchestrator.py`
- `dumbledoer/core/state.py`
- `dumbledoer/core/sandbox.py`
- `dumbledoer/core/planner.py`

## Budget & Quota Tracking
| Session ID | Tokens Used | Budget Remaining |
|---|---|---|

## Task Registry

| Task ID | Title | Type | Status | Owner | Depends On | Session | Checkpoint |
|---------|-------|------|--------|-------|------------|---------|------------|
|T-001|Asyncio Deadlocks Analysis|analysis| completed | — |none|—|none|
|T-002|Split-Brain Sandbox Validation|validation| completed | — |none|—|none|
|T-003|Token Bleed Identification|analysis| completed | — |none|—|none|
|T-004|Exception Swallowing Audit|analysis| completed | — |none|—|none|
|T-005|Execution Pipeline Audit Report|report| completed | — |T-001,T-002,T-003,T-004|—|none|

## Edge Case Coverage
| Edge Case ID (EC-NNN) | Component | Description | Disposition (addressed/dismissed/already-covered) | Task IDs | User Reason |
|---|---|---|---|---|---|

## Task Details


### T-001: Asyncio Deadlocks Analysis
- **Type**: analysis
- **Status**: pending
- **Owner**: —
- **Depends On**: none
- **Assigned Session**: —
- **Description**: Audit orchestrator.py and state.py for QueueEmpty race conditions, unawaited coroutines, and missing _MEMORY_MUTEX / get_registry_lock() acquisitions during state mutations. Write failing tests or static analysis checks to prove vulnerabilities if found.
- **Inputs**: none
- **Outputs**: tests/test_asyncio_deadlocks.py
- **Success Criteria**: A pytest test suite (using live repo data) or a uvx ruff check configuration successfully identifies at least one asyncio deadlock or lock omission, or proves their absence.
- **Estimated Effort**: medium
- **Parallelizable**: yes
- **CodeGraph Impact**: 0 symbols
- **Checkpoint**: none
- **Resume Instructions**: none
- **Notes**: —


### T-002: Split-Brain Sandbox Validation
- **Type**: validation
- **Status**: pending
- **Owner**: —
- **Depends On**: none
- **Assigned Session**: —
- **Description**: Validate sandbox.py to ensure all file writes (write_file_with_review, stage_tmp_write) synchronously mirror changes to .dumbledoer/shadow_* Docker mounts.
- **Inputs**: none
- **Outputs**: tests/test_split_brain_sandbox.py
- **Success Criteria**: Execution of pytest verifies whether file writes accurately sync to Docker shadow mounts using live path structures, failing if split-brain occurs.
- **Estimated Effort**: medium
- **Parallelizable**: yes
- **CodeGraph Impact**: 0 symbols
- **Checkpoint**: none
- **Resume Instructions**: none
- **Notes**: —


### T-003: Token Bleed Identification
- **Type**: analysis
- **Status**: pending
- **Owner**: —
- **Depends On**: none
- **Assigned Session**: —
- **Description**: Inspect planner.py and orchestrator.py for token bleeds such as unbounded `while True` loops in tool execution, missing max_iterations clamps, or repetitive internal doc fetches. Write validation scripts to expose missing loop bounds.
- **Inputs**: none
- **Outputs**: tests/test_token_bleed.py
- **Success Criteria**: A pytest test case triggers loop bounds exhaustion or uvx ruff check exposes missing clamping in execution iterations.
- **Estimated Effort**: medium
- **Parallelizable**: yes
- **CodeGraph Impact**: 0 symbols
- **Checkpoint**: none
- **Resume Instructions**: none
- **Notes**: —


### T-004: Exception Swallowing Audit
- **Type**: analysis
- **Status**: pending
- **Owner**: —
- **Depends On**: none
- **Assigned Session**: —
- **Description**: Audit orchestrator.py to ensure worker() loops safely call queue.task_done() during unhandled runtime crashes, preventing hanging execution waves.
- **Inputs**: none
- **Outputs**: tests/test_exception_swallowing.py
- **Success Criteria**: pytest simulates a runtime crash within a worker() loop and verifies that queue.task_done() is still correctly invoked without hanging.
- **Estimated Effort**: medium
- **Parallelizable**: yes
- **CodeGraph Impact**: 0 symbols
- **Checkpoint**: none
- **Resume Instructions**: none
- **Notes**: —


### T-005: Execution Pipeline Audit Report
- **Type**: report
- **Status**: pending
- **Owner**: —
- **Depends On**: T-001,T-002,T-003,T-004
- **Assigned Session**: —
- **Description**: Synthesize the findings from the asyncio deadlocks, split-brain sandbox, token bleed, and exception swallowing audits into a comprehensive report.
- **Inputs**: none
- **Outputs**: audit_report.md
- **Success Criteria**: audit_report.md contains detailed findings and proposed remediation strategies for all four failure vectors based on the test results.
- **Estimated Effort**: small
- **Parallelizable**: yes
- **CodeGraph Impact**: 0 symbols
- **Checkpoint**: none
- **Resume Instructions**: none
- **Notes**: —

## Change Log
| Task ID | Component | Summary of Change | Validation |
|---|---|---|---|

## Session Log
| Session ID | Start Time | End Time | Tasks Claimed | Outcome | Notes |
|---|---|---|---|---|---|

## Checkpoint Registry
| Checkpoint ID | Task ID | File | Git Hash | Status |
|---|---|---|---|---|

## Open Questions
- None