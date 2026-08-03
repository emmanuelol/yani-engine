# budget-detection: Token Budget Estimation and Graceful Shutdown Algorithm

dumbledoer does not have privileged access to the Gemini API token counter.
Budget is estimated via a running context-size tracker.

---

## Configuration

Budget settings live in `memory.md` Config section:

| Field | Default | Override |
|-------|---------|---------|
| `budget_limit` | 5000000 | Set during `/dumbledoer start` discovery or via `--budget-limit` |
| `budget_threshold_pct` | 80 | Per-session via `--budget-threshold <pct>` flag or by editing `memory.md` Config |

**Threshold computation**: `shutdown_threshold = budget_limit × (budget_threshold_pct / 100)`

Example: `budget_limit=5000000`, `budget_threshold_pct=80` → shutdown at 4,000,000 estimated tokens.

---

## Estimation Algorithm

The parent session maintains a running token estimate:

```
tokens_estimated = 0

On each operation:
  tokens_estimated += estimate_tokens(operation)
```

**Operation cost estimates** (conservative approximations):

| Operation | Estimated Tokens |
|-----------|-----------------|
| Read `memory.md` (full) | 2,000–8,000 (scale with file size) |
| Write checkpoint JSON (small task) | 500–2,000 |
| Sub-agent spawn (overhead) | 1,000 |
| Sub-agent analysis task | 5,000–20,000 |
| Sub-agent change task (small file) | 3,000–10,000 |
| Sub-agent change task (large file) | 10,000–30,000 |
| codegraph_impact query | 200–500 |
| codegraph_context query | 1,000–5,000 |
| User interaction round-trip | 500–2,000 |
| Session Handoff Summary generation | 1,000–3,000 |

Use the UPPER bound of each range for conservative estimation.

---

## Threshold Check (run before each operation)

Before spawning a sub-agent or starting a new task step:

```
remaining = budget_limit - tokens_estimated
if tokens_estimated >= shutdown_threshold:
    TRIGGER GRACEFUL SHUTDOWN
```

If the NEXT planned operation would push over threshold:
- Complete the current atomic step if already in progress.
- Then trigger graceful shutdown.

**Do NOT start a new task if `tokens_estimated + expected_task_cost > shutdown_threshold`.**
Instead, include the task in Session Handoff Summary as "not started."

### Cumulative Token Accounting

Each Gemini API call is stateless — `total_token_count` represents the full request payload (all history + response tokens). For a 10-turn task with 20k average context, actual API cost is ~200k tokens (sum of all calls), NOT 20k. The `budget_limit` must account for this cumulative cost across all parallel workers.

**Example**: 3 parallel workers × 10 tool iterations × 25k avg context = 750,000 tokens per wave.

---

## Graceful Shutdown Sequence (mandatory order)

When threshold is crossed OR approaching:

1. **Complete the current atomic step** — never abandon mid-step. If a sub-agent is
   mid-checkpoint-protocol, let it finish steps 4–6 of checkpoint-protocol.md.

2. **Write checkpoint** — ensure the current task has a valid checkpoint at its current
   step (run Steps 3–6 of checkpoint-protocol.md if not already done).

3. **Update task status** — set the in-progress task to `interrupted` in both Task
   Registry and Task Details. Clear `owner`.

4. **Write session end to Session Log** — update End Time and Outcome:
   - Budget hit: `interrupted-budget`
   - Quota hit: `interrupted-quota`
   - User requested: `interrupted-user`

5. **Update Budget Tracking table** — append row with tokens estimated and outcome.

6. **Generate Session Handoff Summary** — use `templates/session-handoff-template.md`.
   Fill: tasks completed, tasks interrupted (with last checkpoint ID and next action),
   tasks not started, budget status at close, recommended next session scope.

7. **Append Session Handoff Summary to `memory.md`** — append after the Open Questions
   section. This makes it visible in the next session's memory read.

8. **Write session JSON** — write `.dumbledoer/sessions/{sessionId}.json` with full
   execution trace.

9. **Output the Session Handoff Summary** — print it as the final output before ending.

---

## Recommended Next Session Scope (step 6 calculation)

To compute recommended scope for the next session:

```
remaining_budget = budget_limit  # Fresh session starts with full budget
safety_margin = budget_limit × 0.15  # Reserve 15% for overhead and shutdown
usable = budget_limit - safety_margin

for each pending task (in dependency order):
    cost = upper_bound_estimate(task.estimated_effort)
    if usable - cost >= 0:
        include task in recommendation
        usable -= cost
    else:
        stop
```

Effort → cost mapping:
- `small` → 15,000 tokens
- `medium` → 35,000 tokens
- `large` → 70,000 tokens

---

## Budget Tracking Table Entry Format

```
| {sessionId} | {tokens_estimated} | {budget_limit} | {interrupted: yes/no} | {resumed_by: sessionId or —} |
```

`Interrupted` is `yes` for any outcome other than `completed`.
`Resumed By` is filled in by the NEXT session when it resumes this session's tasks.

