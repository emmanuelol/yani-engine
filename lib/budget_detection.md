# Budget Detection Algorithm

This protocol defines the context-window token estimation and graceful shutdown algorithm.

## Token Tracking and Shutdown Flow

1. **Token Estimation**: Track tokens per request/response cycle using model metadata or heuristic counting.
2. **Accumulation**: Add cycle tokens to the `memory.md` "Budget & Quota Tracking" section after each operation.
3. **Threshold Definition**: Maintain a soft threshold (e.g., 80% capacity) and a hard token threshold for the session.
4. **Soft Warning Detection**: When the soft threshold is crossed, log a warning, wrap up non-essential tasks, and prioritize final state commits.
5. **Threshold Crossed**: If the hard token threshold is crossed, immediately trigger a Graceful Shutdown.
6. **Graceful Shutdown**:
   - Pause all execution in the task queue.
   - Commit the current state and checkpoint to `memory.md`.
   - Output a prominent shutdown message indicating token limits were reached.
