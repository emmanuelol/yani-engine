# Installation Guide

## Colleague Installation Workflow

DumbleDoer has transitioned from centralized wrappers and bash aliases into a natively distributable extension for the `agy` client.

### 1. Install the CLI Tool Globally

Installing via `uv tool` automatically isolates all dependencies while exposing the `dumbledoer` executable globally across your entire system.

```bash
uv tool install git+https://github.com/your-org/DumbleDoer.git
```

### 2. Load the Plugin into the agy Client

DumbleDoer includes a native `plugin.json` manifest. You load the plugin in your `agy` client to natively discover its tools and MCP servers (without shell hacks):

```bash
agy --plugin-dir ~/.local/share/uv/tools/dumbledoer
```

### 3. Quick Start

Once loaded, you can natively trigger DumbleDoer directly from your `agy` prompt:

```text
/dumbledoer start
```

Or from any standard terminal window in your target directory:

```bash
cd ~/projects/my-target-repo
dumbledoer start --docs ./docs
```
