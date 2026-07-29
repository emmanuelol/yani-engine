import os
import sys

def patch_file(filepath):
    with open(filepath, "r") as f:
        content = f.read()

    old_text = "2. Use the `execute_bash` tool to actively test the code within the Docker sandbox. Run syntax checkers (e.g., `python -m py_compile`, `uv run pytest`), type checkers, or execute the target scripts to verify they do not throw errors."
    new_text = "2. **Static Analysis & Dry-Runs (HARDENED):** You MUST run a modern static analysis tool (e.g., `uvx ruff check <file>` or `flake8 <file>`) on all modified Python files to catch `NameError`, `ImportError`, and undefined variables. `py_compile` is strictly prohibited as a standalone check because it misses runtime variable errors. You MUST also execute the target scripts as a dry-run to verify they do not throw immediate runtime exceptions."

    if old_text in content:
        content = content.replace(old_text, new_text)
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Patched {filepath}")
    else:
        print(f"Warning: Text not found in {filepath}")

patch_file("/home/emmanuel/Documentos/GitHub/DumbleDoer/skills/audit/INSTRUCTIONS.md")
patch_file(os.path.expanduser("~/.gemini/config/plugins/dumbledoer/skills/audit/INSTRUCTIONS.md"))
