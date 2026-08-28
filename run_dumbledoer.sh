#!/usr/bin/env bash
# run_dumbledoer.sh - Backward compatibility wrapper forwarding to run_yani.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/run_yani.sh" "$@"
