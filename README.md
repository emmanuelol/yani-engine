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

3. **Model Tiering:** DumbleDoer uses a default model for basic orchestration, but you can override this to utilize advanced reasoning models. You can do this by setting the `AGY_MODEL` environment variable (e.g., `export AGY_MODEL="gemini-2.5-pro"`) or by passing the `--model` flag (e.g., `--model gemini-2.5-pro`) when running commands.

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
* **VS Code Diff-Gate**: A Human-in-the-Loop review system intercepts any file modifications. DumbleDoer will automatically open a diff in your active VS Code instance, allowing you to explicitly approve or reject the agent's proposed changes. If VS Code is unavailable (e.g. running in an SSH session without GUI), you can pass the `--no-gui` flag to fall back to a terminal-native `rich` diff.
* **Zero-Trust Docker Sandbox**: Sub-agents execute testing and validation within an isolated Docker sandbox. Note: **this requires the host Docker daemon to be running** for DumbleDoer to execute bash commands, run test suites, or interact with external dependencies securely.

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
  Executes the registered tasks in dependency order. It utilizes concurrent Gemini calls where there are no overlapping output files. Changes are automatically approved by default unless you pass the `-v` (verbose) flag for manual Diff-Gate review. Rich progress bars visualize task advancement directly in the terminal. If token bloat is detected, it invokes RTK to clean the workspace.

* **/dumbledoer resume**
  Detects interrupted tasks or stale locks, offering you options to safely resume from a checkpoint, roll back, or defer the task.

* **/dumbledoer rollback**
  Safely restores files from the `.dumbledoer/rollbacks/` directory and resets the current task status back to pending.

* **/dumbledoer report**
  Generates a quantitative before/after improvement report detailing the CodeGraph impact radius and providing delta summaries of the optimizations.

* **/dumbledoer update-docs**
  Syncs your project's documentation with the current codebase utilizing CodeGraph structural analysis to ensure everything is up to date.

---

## 🗺️ Roadmap: Next Stage (The Unified CLI)

Our ultimate vision for DumbleDoer is to seamlessly fuse the conversational UX of traditional chatbots (like Kandalf/Antigravity) with DumbleDoer's powerful, parallel execution factory into a single, unified standalone CLI application.

### The Fused Architecture

1. **The Unified Entrypoint**: The main entry point will become a persistent conversational loop. You are dropped into a stateful, interactive interface where you can chat, brainstorm, and plan architecture with full access to Context7 and CodeGraph MCP servers.
2. **The Tooling Handoff**: Instead of the LLM sequentially and slowly editing code directly in the chat, it will use a new internal tool: `dispatch_execution_wave(tasks)`.
3. **The Parallel Factory Takes Over**: The moment a plan is agreed upon, the chat loop pauses. DumbleDoer natively activates its headless parallel execution engine—building the dependency graph, firing off concurrent LLM API calls, and generating the files simultaneously.
4. **Interactive Terminal Diff-Gate**: The terminal-native diff UI presents the changes for review instantly.
5. **Context Flush and Return**: Once the wave is merged and audited by the native QA harness loop, the chat history context is flushed to prevent context bloat, and control is returned to the chat loop for your next command.
