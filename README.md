# 🧙‍♂️ DumbleDoer

> An advanced, system-wide Agent Engineering Harness for Antigravity (`agy`).

Welcome to **DumbleDoer**! 👋 DumbleDoer is an advanced, autonomous framework designed to give your AI agent the tools, constraints, and state-tracking necessary to safely audit, refactor, and optimize complex software repositories.

It operates on a **"Zero-Copy Plugin"** model. Instead of polluting every target repository with agent scripts, it acts as a native plugin for the `agy` client, running out of one centralized location on your machine.

---

## 🚀 Core Technologies

Under the hood, DumbleDoer leverages powerful, modern tools to give you the safest and most efficient agentic experience:

* **MCP (Model Context Protocol):** Connects to specialized servers like **CodeGraph** (for blast radius analysis) and **Context7** (for semantic search).
* **[uv](https://github.com/astral-sh/uv):** Used for lightning-fast, isolated Python environments.
* **RTK (Rust Token Killer):** Integrates this custom system tool to forcefully optimize memory and clear token bloat during heavy architectural refactors.

---

## 📋 Prerequisites & Requirements

Before we cast any spells, you need a few core components installed on your system. Here is exactly what they are and why DumbleDoer needs them:

* **Node.js (v20+):** The JavaScript runtime environment. DumbleDoer uses Node to execute `npx` commands that spin up the CodeGraph and Context7 MCP servers to semantically map your codebase.
* **uv:** A ridiculously fast Python package manager. It acts as the engine for your DumbleDoer environment, building a strictly isolated `.venv/` sandbox and syncing dependencies so it never clutters or modifies your system Python.
* **RTK (Rust Token Killer):** A custom binary/system tool. When DumbleDoer detects excessive memory usage or token bloat during an audit, it automatically invokes RTK to aggressively clean the environment before proceeding.
* **agy (Antigravity CLI):** The overarching AI client terminal where DumbleDoer lives natively as a registered plugin.

---

## 🔑 Authentication (Crucial Step: BYOK)

DumbleDoer operates on a **Bring Your Own Key (BYOK)** model. Because it runs its own isolated Gemini intelligence engine to formulate plans and spawn sub-agents, you will need a free Google API key for it to function.

1. **Get your API Key:** Generate a free Google API key from Google AI Studio.
2. **Export Globally:** You *must* export this key globally in your terminal profile so the Antigravity client can automatically hand it down to DumbleDoer as a child process.

Add the following line to your terminal profile (e.g., `~/.bashrc` or `~/.zshrc`):

```bash
export GOOGLE_API_KEY="your-api-key-here"
```

Don't forget to reload your profile or restart your terminal:

```bash
source ~/.bashrc # or source ~/.zshrc
```

3. **Model Tiering:** DumbleDoer defaults to `gemini-2.5-flash` for orchestration, but you can override this to utilize advanced reasoning models. You can do this by setting the `AGY_MODEL` environment variable (e.g., `export AGY_MODEL="gemini-2.5-pro"`) or by passing the `--model` flag (e.g., `--model gemini-2.5-pro`) when running commands.

---

## 🛠️ Installation

Installing DumbleDoer is incredibly straightforward. You install it as a native plugin to `agy` by pointing it to your local repository clone.

1. Clone this repository to your local machine:
```bash
git clone <repository-url>
cd DumbleDoer
```

2. Install the plugin natively via `agy`:
```bash
agy plugin install ./
```

That's it! DumbleDoer is now hooked into your `agy` environment. 🎉

---

## 🛡️ VS Code Diff-Gate & Zero-Trust Sandbox

DumbleDoer prioritizes safety during execution:
* **VS Code Diff-Gate (Option B Flow)**: File changes are written directly to disk so that test runners (`pytest`, `ruff`, etc.) always validate against the actual updated code. A shadow `.tmp` copy is simultaneously created for the diff review workflow. If you reject a change during review, DumbleDoer automatically restores the original file from its rollback backup (`.dumbledoer/rollbacks/`). If VS Code is unavailable (e.g. running in an SSH session without GUI), you can pass the `--no-gui` flag to fall back to a terminal-native `rich` diff.
* **Zero-Trust Docker Sandbox**: Sub-agents execute testing and validation within an isolated Docker sandbox. Note: **this requires the host Docker daemon to be running** for DumbleDoer to execute bash commands, run test suites, or interact with external dependencies securely.

---

## ⚡ Token Optimization Architecture

DumbleDoer employs several techniques to minimize API token consumption across multi-turn sessions:

* **Dynamic Tool Filtering**: Each command receives only the tool definitions it actually needs. For example, `iterate` gets only `add_task`, `read_file`, and `codegraph_search` — saving ~15,000–20,000 input tokens per call versus loading all 60–100 tools.
* **Sliced Memory Ingestion**: The `iterate` command injects only the `## Project Goal`, `## Scope`, and `## Task Registry` sections from `memory.md` instead of the full file — saving ~10,000–30,000 tokens per call.
* **Selective MCP Initialization**: Commands that don't need structural code analysis (`status`, `rollback`, `report`) skip CodeGraph and Context7 MCP server startup entirely.
* **Mid-Loop Budget Enforcement**: The `BudgetManager` checks token consumption after every tool response cycle (not just at the end of a task), preventing unbounded token growth during long tool loops.
* **Degraded Tool Loop Breaker**: If CodeGraph MCP servers are unavailable, dummy fallback tools are injected. After 3 consecutive degraded tool calls, the engine injects a `STOP` directive forcing the LLM to switch to alternatives — preventing infinite retry loops.

---

## 🔒 Concurrency Safety

DumbleDoer executes tasks in parallel waves via `asyncio.gather`. To prevent state corruption:

* **Unified Locking**: `memory.md` updates acquire both a thread-level `RLock` and a process-level `FileLock`, protecting against races in both parallel async tasks and multi-process sub-agents.
* **Ambiguity Guard**: The `update_memory_registry` tool rejects replacement targets that match multiple locations in `memory.md`, preventing silent state corruption from ambiguous `str.replace()` calls.
* **Orphan Recovery Safety**: The `OrphanRecoveryScanner` skips `.tmp` files younger than 60 seconds, preventing deletion of files being actively written by concurrent sub-agents.
* **Backoff Cap**: API rate-limit retries are capped at 120 seconds total wait time, preventing indefinite stalls that block dependent execution waves.

---

## 🔄 The Workflow & Command Summary

DumbleDoer integrates deeply into your development lifecycle with a suite of native slash commands.

### ⚡ Auto-Activation

DumbleDoer is smart. The `hooks/on-workspace-load.md` script triggers automatically whenever `agy` loads a directory containing a `memory.md` file. The agent will immediately read the memory file, adopt the DumbleDoer persona, and summarize the current engineering task.

### 🧠 Core Architecture Highlights

* **Manual Execution Loop:** Unlike standard clients relying on fragile SDK auto-calling loops that often drop complex native commands, DumbleDoer uses a custom, manual `_run_with_tools` execution engine. This guarantees that internal `async` tools (like `execute_bash` or dynamically generated `mcp_wrapper` calls) are correctly routed, awaited, and validated in an unbroken execution loop.
* **Total Instruction Isolation:** The logic dictating the behavior of inner agents is completely decoupled into `INSTRUCTIONS.md` files for each skill. This prevents Antigravity's outer context window from leaking into the inner sub-agents, preserving strict boundary execution without hallucination.

### Command Registry

You can interact with DumbleDoer using the following slash commands within `agy`:

* **/dumbledoer start**
  Ingests documentation, conducts a Discovery Q&A, performs edge-case detection, and registers an atomic task plan in the `memory.md` file.

* **/dumbledoer execute**
  Executes the registered tasks in dependency order. It utilizes concurrent Gemini calls where there are no overlapping output files. Changes are applied directly to disk (with rollback backups) and auto-approved by default unless you pass the `-v` (verbose) flag for manual Diff-Gate review. Rich progress bars visualize task advancement directly in the terminal. If token bloat is detected, it invokes RTK to clean the workspace.

* **/dumbledoer iterate**
  Evaluates a user prompt against the current project state and decomposes it into atomic tasks, registering them in the Task Registry. Uses sliced memory ingestion and filtered tools for minimal token consumption.

* **/dumbledoer audit**
  Runs the QA Harness Loop — evaluates completed tasks against their success criteria and autonomously generates fix tasks if bugs are found.

* **/dumbledoer resume**
  Detects interrupted tasks or stale locks, offering you options to safely resume from a checkpoint, roll back, or defer the task.

* **/dumbledoer rollback**
  Safely restores files from the `.dumbledoer/rollbacks/` directory and resets the current task status back to pending.

* **/dumbledoer report**
  Generates a quantitative before/after improvement report detailing the CodeGraph impact radius and providing delta summaries of the optimizations.

* **/dumbledoer update-docs**
  Syncs your project's documentation with the current codebase utilizing CodeGraph structural analysis to ensure everything is up to date.

* **/dumbledoer status**
  Shows the Task Registry, session summary, budget usage, and CodeGraph health for the current improvement session.

---

## 🗺️ Roadmap: Next Stage (The Unified CLI)

Our ultimate vision for DumbleDoer is to seamlessly fuse the conversational UX of traditional chatbots (like Kandalf/Antigravity) with DumbleDoer's powerful, parallel execution factory into a single, unified standalone CLI application.

### The Fused Architecture

1. **The Unified Entrypoint**: The main entry point will become a persistent conversational loop. You are dropped into a stateful, interactive interface where you can chat, brainstorm, and plan architecture with full access to Context7 and CodeGraph MCP servers.
2. **The Tooling Handoff**: Instead of the LLM sequentially and slowly editing code directly in the chat, it will use a new internal tool: `dispatch_execution_wave(tasks)`.
3. **The Parallel Factory Takes Over**: The moment a plan is agreed upon, the chat loop pauses. DumbleDoer natively activates its headless parallel execution engine—building the dependency graph, firing off concurrent LLM API calls, and generating the files simultaneously.
4. **Interactive Terminal Diff-Gate**: The terminal-native diff UI presents the changes for review instantly.
5. **Context Flush and Return**: Once the wave is merged and audited by the native QA harness loop, the chat history context is flushed to prevent context bloat, and control is returned to the chat loop for your next command.
