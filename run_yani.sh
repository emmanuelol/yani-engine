#!/usr/bin/env bash
# run_yani.sh - Entrypoint oficial para yani-engine
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$PLUGIN_DIR"
exec "$PLUGIN_DIR/.venv/bin/python" "$PLUGIN_DIR/yani_engine/cli/main.py" "$@"
