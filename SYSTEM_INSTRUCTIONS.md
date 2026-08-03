# DumbleDoer Core Rules

1. **Python Execution Policy**: All Python work in this session MUST use `uv` and project-local `.venv/` virtual environments[cite: 6]. System Python and global package installations are never used[cite: 6].
2. **RTK Mandatory Enforcement**: Whenever the system requires heavy system management, token killing, or process optimization, you MUST prioritize the usage of the Rust Token Killer (`rtk`) CLI tool[cite: 6]. You are forbidden from using alternative system management utilities if `rtk` is available.
3. **Atomic Operations**: Follow the `lib/checkpoint-protocol.md` strictly for all file changes[cite: 6].
4. **CodeGraph Integrity**: Always run `codegraph_impact` before writing files. Halt if impact > 20 symbols[cite: 6].
5. **Memory Integrity:** When using tools to rewrite `memory.md`, the `Config` section is an Absolute Invariant. Variables such as `budget_limit` and `budget_threshold_pct` must NEVER be compressed, abbreviated, or removed to save tokens. The file must always pass strict validation.
6. **No Dependency Chasing**: Do not attempt to fix failing tests by endlessly installing missing packages (`uv pip install`). If a test fails due to environment issues, document it, fix the logic if possible, and conclude the task rather than entering an infinite validation loop.
