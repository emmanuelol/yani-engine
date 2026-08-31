#!/usr/bin/env python3
"""validate_tape.py — Deterministic pre-flight validator for VHS .tape files.

Checks:
  1. Required directives: Output, Set FontSize, Set Width, Set Height, Set Theme
  2. Dangerous command blocklist (rm -rf, DROP, git push --force, etc.)
  3. Valid Sleep durations (parseable, within bounds)
  4. No secrets patterns (API keys, tokens)

Exit codes:
  0 — Tape is valid.
  1 — Validation errors found. JSON report printed to stdout.

Usage:
  python3 validate_tape.py <tape_file>
"""

import json
import re
import sys
from pathlib import Path

# --- Configuration ---

REQUIRED_DIRECTIVES = [
    r"^Output\s+\S+",
    r"^Set\s+FontSize\s+\d+",
    r"^Set\s+Width\s+\d+",
    r"^Set\s+Height\s+\d+",
    r'^Set\s+Theme\s+"[^"]+"',
]

REQUIRED_DIRECTIVE_NAMES = [
    "Output <filename>",
    "Set FontSize <n>",
    "Set Width <n>",
    "Set Height <n>",
    'Set Theme "<name>"',
]

DANGEROUS_PATTERNS = [
    (r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|--recursive)\s", "Destructive rm command"),
    (r"rm\s+-[a-zA-Z]*f[a-zA-Z]*r\s", "Destructive rm command"),
    (r"mkfs\.", "Filesystem format command"),
    (r"dd\s+if=", "Raw disk write command"),
    (r"DROP\s+(TABLE|DATABASE|SCHEMA)", "SQL destructive command"),
    (r"TRUNCATE\s+TABLE", "SQL destructive command"),
    (r"git\s+push\s+.*--force", "Force push"),
    (r"git\s+push\s+-f\b", "Force push"),
    (r"curl\s+.*\|\s*(bash|sh)", "Pipe to shell anti-pattern"),
    (r"wget\s+.*\|\s*(bash|sh)", "Pipe to shell anti-pattern"),
    (r"chmod\s+777\s", "Insecure permissions"),
    (r"sudo\s+rm\s", "Destructive sudo rm"),
]

SECRET_PATTERNS = [
    (r"(sk|pk|api[_-]?key)[_-]?[a-zA-Z0-9]{20,}", "Possible API key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub personal access token"),
    (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth token"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key ID"),
    (r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.", "JWT token"),
]

SLEEP_PATTERN = re.compile(r"^Sleep\s+(\d+(?:\.\d+)?)(ms|s)$")
MAX_SLEEP_SECONDS = 30.0
MAX_TOTAL_SLEEP_SECONDS = 120.0


def validate_tape(filepath: str) -> dict:
    """Validate a .tape file and return structured results."""
    errors: list[dict] = []
    warnings: list[dict] = []

    path = Path(filepath)
    if not path.exists():
        return {"valid": False, "errors": [{"line": 0, "message": f"File not found: {filepath}"}]}

    if path.suffix != ".tape":
        return {"valid": False, "errors": [{"line": 0, "message": f"Expected .tape extension, got: {path.suffix}"}]}

    lines = path.read_text(encoding="utf-8").splitlines()

    if not lines:
        return {"valid": False, "errors": [{"line": 0, "message": "Tape file is empty"}]}

    # --- Check required directives ---
    for directive, name in zip(REQUIRED_DIRECTIVES, REQUIRED_DIRECTIVE_NAMES):
        found = any(re.match(directive, line.strip()) for line in lines)
        if not found:
            errors.append({"line": 0, "message": f"Missing required directive: {name}"})

    # --- Line-by-line checks ---
    total_sleep_seconds = 0.0

    for i, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue

        # Check dangerous commands inside Type directives
        if line.startswith("Type "):
            typed_content = line[5:].strip().strip('"').strip("'")
            for pattern, description in DANGEROUS_PATTERNS:
                if re.search(pattern, typed_content, re.IGNORECASE):
                    errors.append({"line": i, "message": f"Dangerous command blocked: {description}"})

            for pattern, description in SECRET_PATTERNS:
                if re.search(pattern, typed_content):
                    errors.append({"line": i, "message": f"Possible secret detected: {description}"})

        # Validate Sleep durations
        if line.startswith("Sleep "):
            match = SLEEP_PATTERN.match(line)
            if match:
                value = float(match.group(1))
                unit = match.group(2)
                seconds = value / 1000.0 if unit == "ms" else value

                if seconds > MAX_SLEEP_SECONDS:
                    errors.append({
                        "line": i,
                        "message": f"Sleep duration too long: {seconds}s (max {MAX_SLEEP_SECONDS}s)",
                    })

                total_sleep_seconds += seconds
            else:
                errors.append({"line": i, "message": f"Invalid Sleep syntax: {line}"})

    # Total duration check
    if total_sleep_seconds > MAX_TOTAL_SLEEP_SECONDS:
        warnings.append({
            "line": 0,
            "message": f"Total sleep duration is {total_sleep_seconds:.1f}s (recommended max {MAX_TOTAL_SLEEP_SECONDS}s)",
        })

    result = {
        "valid": len(errors) == 0,
        "file": str(path),
        "total_lines": len(lines),
        "total_sleep_seconds": round(total_sleep_seconds, 1),
        "errors": errors,
        "warnings": warnings,
    }

    return result


def main() -> None:
    if len(sys.argv) != 2:
        print(json.dumps({"valid": False, "errors": [{"line": 0, "message": "Usage: validate_tape.py <tape_file>"}]}))
        sys.exit(1)

    result = validate_tape(sys.argv[1])
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
