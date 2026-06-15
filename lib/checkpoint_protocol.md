# Checkpoint Protocol

This ruleset outlines a 6-step atomic write and rollback safety system that must be strictly followed by all Gemini sub-agents.

## The 6-Step Atomic Write System

1. **Write rollback copy**: Copy the target file to a designated `.dumbledoer/rollbacks/` directory with a precise timestamp.
2. **Write Intent to Change Log**: Record the intended change in the `memory.md` Change Log section with a "Pending" status.
3. **Write Checkpoint File**: Create a state checkpoint snapshot capturing the current task and system state in the Checkpoint Registry.
4. **Write New Content to Temp File**: Generate the new modified content into a temporary file alongside the target file.
5. **Atomic Rename**: Perform an atomic rename operation (e.g., `os.rename`) to replace the old target file with the new temporary file.
6. **Update Change Log to Applied**: Mark the intent in the `memory.md` Change Log as "Applied".
