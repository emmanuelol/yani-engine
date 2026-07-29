# Installation Guide

## Colleague Installation Workflow

DumbleDoer is a natively distributable extension for the `agy` client. It runs in a "Zero-Copy" manner without polluting your target repositories.

### Prerequisites

Before installing DumbleDoer, ensure you have the following core components installed on your system:

- **Node.js (v20+)**: Required for running `npx` commands that spin up the CodeGraph and Context7 MCP servers.
- **uv**: A fast Python package manager. It acts as the engine for building strictly isolated `.venv/` sandboxes and syncing dependencies without modifying your system Python.
- **RTK (Rust Token Killer)**: A custom binary/system tool that automatically optimizes memory and clears token bloat during heavy architectural refactors.
- **agy (Antigravity CLI)**: The overarching AI client terminal where DumbleDoer lives natively as a registered plugin.

### 1. Clone the Repository

First, clone the DumbleDoer repository to a dedicated location on your machine:

```bash
git clone <repository-url>
cd DumbleDoer
```

### 2. Install the Plugin into the agy Client

DumbleDoer includes a native `plugin.json` manifest. You can install the plugin natively into your `agy` client by running the following command from within the cloned directory:

```bash
agy plugin install ./
```

This registers DumbleDoer globally in your `agy` client, seamlessly integrating its skills, slash commands, and sub-agents.

### 3. Model Configuration & BYOK

DumbleDoer requires a Gemini API key. Ensure `GOOGLE_API_KEY` is exported in your environment. You must export this key globally in your terminal profile so the Antigravity client can automatically hand it down to DumbleDoer as a child process.

```bash
export GOOGLE_API_KEY="your-api-key-here"
```

By default, DumbleDoer uses a lightweight model. You can override this to use advanced reasoning models (like `gemini-2.5-pro`) by setting the `AGY_MODEL` environment variable or passing the `--model` flag:

```bash
export AGY_MODEL="gemini-2.5-pro"
```

### 4. Zero-Trust Sandbox Requirement

DumbleDoer utilizes a **Zero-Trust Docker Sandbox** for bash execution and testing. **You must have the Docker daemon running on your host machine** for tasks that require isolated execution.

### 5. Quick Start

Once loaded, you can natively trigger DumbleDoer directly from your `agy` prompt in any target repository:

```text
/dumbledoer start
```
Or from any standard terminal window in your target directory:

```bash
cd ~/projects/my-target-repo
agy --model gemini-2.5-pro
# Then trigger /dumbledoer start inside agy
```
