#!/usr/bin/env bash
# run_yani.sh - Entrypoint oficial para yani-engine
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$PLUGIN_DIR"

if [ -f "$PLUGIN_DIR/.venv/bin/python" ]; then
    PYTHON_EXEC="$PLUGIN_DIR/.venv/bin/python"
else
    PYTHON_EXEC="python3"
fi

exec "$PYTHON_EXEC" "$PLUGIN_DIR/yani_engine/cli/main.py" "$@"
