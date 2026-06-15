# DumbleDoer Agent Engineering Harness

DumbleDoer is a powerful agentic engineering harness and autonomous workflow powered by Gemini. It acts as a globally installable, natively distributable extension for the `agy` client.

## Colleague Installation

DumbleDoer is packaged as a globally installable CLI tool. Installing via `uv tool` automatically isolates the dependencies while exposing the `dumbledoer` executable globally to your system.

### 1. Install Globally
Colleagues should install the harness globally using `uv`:

```bash
uv tool install git+https://github.com/your-org/DumbleDoer.git
```

### 2. Load the Plugin
Colleagues can then natively load the plugin into their `agy` client so that its slash commands and MCP servers are registered automatically:

```bash
agy --plugin-dir ~/.local/share/uv/tools/dumbledoer
```

## Usage

With the plugin loaded and the executable registered, you can invoke DumbleDoer natively via slash command within `agy` or from your terminal anywhere:

```bash
dumbledoer start --docs ./docs
```

DumbleDoer will dynamically run zero-copy semantic audits against your current active directory.

For more details, see the [Documentation Vault](docs/01-installation.md).
