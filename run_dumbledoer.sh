#!/usr/bin/env bash
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$PLUGIN_DIR"
exec "$PLUGIN_DIR/.venv/bin/python" "$PLUGIN_DIR/dumbledoer/dumbledoer_cli.py" "$@"
