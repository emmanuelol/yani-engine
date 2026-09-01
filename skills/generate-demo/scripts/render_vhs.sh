#!/usr/bin/env bash
# render_vhs.sh — Deterministic VHS rendering wrapper for yani-engine
# Isolates vhs stderr noise (headless Chromium logs) from LLM context.
# Returns ONLY the output GIF path on success.
#
# Usage: bash render_vhs.sh <tape_file> [--output-dir <dir>]
#
# Exit codes:
#   0 — Success, GIF rendered. stdout contains absolute path to GIF.
#   1 — Input validation error.
#   2 — vhs binary not found.
#   3 — vhs rendering failed.

set -euo pipefail

# --- Argument Parsing ---
TAPE_FILE=""
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -*)
            echo '{"error": "Unknown flag: '"$1"'", "exit_code": 1}' >&2
            exit 1
            ;;
        *)
            if [[ -z "$TAPE_FILE" ]]; then
                TAPE_FILE="$1"
            else
                echo '{"error": "Multiple tape files specified. Provide exactly one.", "exit_code": 1}' >&2
                exit 1
            fi
            shift
            ;;
    esac
done

# --- Input Validation ---
if [[ -z "$TAPE_FILE" ]]; then
    echo '{"error": "No tape file specified. Usage: render_vhs.sh <tape_file>", "exit_code": 1}' >&2
    exit 1
fi

if [[ ! -f "$TAPE_FILE" ]]; then
    echo '{"error": "Tape file not found: '"$TAPE_FILE"'", "exit_code": 1}' >&2
    exit 1
fi

if [[ "${TAPE_FILE##*.}" != "tape" ]]; then
    echo '{"error": "File must have .tape extension: '"$TAPE_FILE"'", "exit_code": 1}' >&2
    exit 1
fi

# --- Binary Check ---
if ! command -v vhs &>/dev/null; then
    echo '{"error": "vhs binary not found. Ensure vhs is installed in yani-base:latest container.", "exit_code": 2}' >&2
    exit 2
fi

# --- Resolve Output Path ---
# Extract the Output directive from the tape file to know expected filename
OUTPUT_FILENAME=$(grep -m1 '^Output ' "$TAPE_FILE" | sed 's/^Output //' | xargs)

if [[ -z "$OUTPUT_FILENAME" ]]; then
    echo '{"error": "Tape file missing required Output directive.", "exit_code": 1}' >&2
    exit 1
fi

# If custom output dir specified, modify the tape's output location
WORK_DIR=$(dirname "$(realpath "$TAPE_FILE")")
if [[ -n "$OUTPUT_DIR" ]]; then
    mkdir -p "$OUTPUT_DIR"
    WORK_DIR="$(realpath "$OUTPUT_DIR")"
fi

# --- Render ---
# Capture stderr to temp file to isolate Chromium noise from LLM context
VHS_LOG=$(mktemp /tmp/vhs-render-XXXXXX.log)
trap 'rm -f "$VHS_LOG"' EXIT

if vhs "$TAPE_FILE" --output "$WORK_DIR/$OUTPUT_FILENAME" >"$VHS_LOG" 2>&1; then
    RESULT_PATH="$(realpath "$WORK_DIR/$OUTPUT_FILENAME")"
    if [[ -f "$RESULT_PATH" ]]; then
        echo "$RESULT_PATH"
        exit 0
    else
        echo '{"error": "vhs reported success but output file not found: '"$RESULT_PATH"'", "exit_code": 3}' >&2
        exit 3
    fi
else
    VHS_EXIT=$?
    # Extract only the last 20 lines of vhs output to avoid flooding context
    TAIL_LOG=$(tail -20 "$VHS_LOG")
    echo '{"error": "vhs rendering failed", "exit_code": 3, "vhs_exit": '"$VHS_EXIT"', "log_tail": "'"$(echo "$TAIL_LOG" | tr '\n' '\\n' | sed 's/"/\\"/g')"'"}' >&2
    exit 3
fi
