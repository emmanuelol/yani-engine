# 🧙‍♂️ DumbleDoer

> An advanced, system-wide Agent Engineering Harness for Antigravity (`agy`).

Welcome to **DumbleDoer**! 👋 DumbleDoer is an advanced, autonomous framework designed to give your AI agent the tools, constraints, and state-tracking necessary to safely audit, refactor, and optimize complex software repositories.

It operates on a **"Zero-Copy Plugin"** model. Instead of polluting every target repository with agent scripts, it acts as a native plugin for the `agy` client, running out of one centralized location on your machine.

---

## 🚀 Core Technologies

Under the hood, DumbleDoer leverages powerful, modern tools to give you the safest and most efficient agentic experience:

* **MCP (Model Context Protocol):** Connects to specialized servers like **CodeGraph** (for rigorous blast radius analysis) and **Context7** (for deep semantic search).
* **[uv](https://github.com/astral-sh/uv):** Used for lightning-fast, isolated Python environments, ensuring system Python integrity.
* **RTK (Rust Token Killer):** Integrates this custom system tool to forcefully optimize memory and clear token bloat during heavy architectural refactors.

---

## 🛠️ Installation

Installing DumbleDoer is incredibly straightforward. You install it as a native plugin to `agy` by pointing it to your local repository clone.

1. Clone this repository to your local machine:
```bash
git clone <repository-url>
cd DumbleDoer
```

2. Install the plugin natively via `agy` (Global Client Linking):
```bash
agy plugin install ./
```

That's it! DumbleDoer is now hooked into your `agy` environment. 🎉

---

## 🔑 Authentication & Prerequisites

DumbleDoer operates on a **Bring Your Own Key (BYOK)** model. You must export a Google API key globally in your terminal profile so the Antigravity client can pass it down.

```bash
export GOOGLE_API_KEY="your-api-key-here"
```

* **Node.js (v20+):** Required to run `npx` commands for MCP servers.
* **Model Tiering:** DumbleDoer defaults to lightweight models, but you can override this for complex tasks using `export AGY_MODEL="gemini-2.5-pro"`.

---

## 🛡️ Security Features

DumbleDoer prioritizes safety during execution with two primary mechanisms:
* **VS Code Diff-Gate**: File changes are written to a shadow `.tmp` copy while the original is backed up. If you reject a change during review, DumbleDoer automatically restores the original file. If VS Code is unavailable, a terminal-native `rich` diff is used.
* **Zero-Trust Docker Sandbox**: Sub-agents execute testing and validation within an isolated Docker sandbox. *(Requires the host Docker daemon to be running).*

---

## ⚡ Token Optimization Architecture

DumbleDoer employs advanced strategies to minimize API token consumption:
* **Caveman Integration**: Enforces ultra-compressed communication, cutting token usage by up to 75%.
* **Dynamic Tool Filtering**: Commands receive only the exact tools they need.
* **Sliced Memory Ingestion**: Injects only targeted sections of `memory.md` during loops.
* **Mid-Loop Budget Enforcement**: Validates token budgets after every tool cycle to prevent unbounded consumption.

---

## 🔒 Concurrency Safety

DumbleDoer executes tasks in parallel waves via `asyncio.gather`. To prevent state corruption:
* **Unified Locking**: `memory.md` updates acquire both a thread-level `RLock` and a process-level `FileLock`.
* **Ambiguity Guard**: Prevents silent state corruption from ambiguous `str.replace()` calls in the registry.
* **Import Coupling Analysis**: Pre-write file ownership checks prevent race conditions between sub-agents modifying interrelated files.

---

## 🔄 The Workflow & Command Summary

DumbleDoer integrates deeply into your development lifecycle with a suite of native slash commands.

* **/dumbledoer start**: Ingests documentation and maps out an atomic task plan.
* **/dumbledoer execute**: Executes registered tasks in dependency order.
* **/dumbledoer iterate**: Evaluates user prompts against the current state and decomposes into tasks.
* **/dumbledoer audit**: Runs the QA Harness Loop to autonomously generate fixes.
* **/dumbledoer resume**: Detects interrupted tasks and offers recovery options.
* **/dumbledoer rollback**: Safely restores files from checkpoints.
* **/dumbledoer report**: Generates an improvement report detailing CodeGraph impact.
* **/dumbledoer update-docs**: Syncs documentation with the current codebase.
* **/dumbledoer status**: Shows the Task Registry and CodeGraph health.

---

## 🗺️ Roadmap: Next Stage (The Unified CLI)

Our ultimate vision for DumbleDoer is to seamlessly fuse the conversational UX of traditional chatbots (like Antigravity) with DumbleDoer's powerful, parallel execution factory into a single, unified standalone CLI application.

### The Fused Architecture

1. **The Unified Entrypoint**: A persistent conversational loop with full Context7 and CodeGraph access.
2. **The Tooling Handoff**: The LLM will dispatch execution waves dynamically.
3. **The Parallel Factory Takes Over**: Headless parallel execution engine builds dependency graphs and fires off concurrent API calls.
4. **Interactive Terminal Diff-Gate**: Review changes instantly in the terminal.
5. **Context Flush**: Flushes chat history to prevent context bloat, returning control to the chat loop safely.
