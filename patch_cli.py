import os
import shutil

src_file = "dumbledoer/dumbledoer_cli.py"
tmp_dir = ".dumbledoer/tmp"
tmp_file = os.path.join(tmp_dir, "dumbledoer_cli.py.tmp")

os.makedirs(tmp_dir, exist_ok=True)

with open(src_file, "r") as f:
    content = f.read()

# Add import
if "from filelock import FileLock" not in content:
    content = content.replace("import sys\n", "import sys\nfrom filelock import FileLock\n")

# Replace update_memory_registry
old_func = """def update_memory_registry(content: str) -> str:
    \"\"\"Updates the memory.md file with the provided content.
    CRITICAL CONSTRAINT: You MUST preserve the entire Config block exactly as it was, including 'budget_limit' and 'budget_threshold_pct'. Do not compress, omit, or truncate the Config section under any circumstances.
    \"\"\"
    return write_file("memory.md", content)"""

new_func = """def update_memory_registry(content: str) -> str:
    \"\"\"Updates the memory.md file with the provided content.
    CRITICAL CONSTRAINT: You MUST preserve the entire Config block exactly as it was, including 'budget_limit' and 'budget_threshold_pct'. Do not compress, omit, or truncate the Config section under any circumstances.
    \"\"\"
    with FileLock("memory.md.lock", timeout=10):
        return write_file("memory.md", content)"""

content = content.replace(old_func, new_func)

with open(tmp_file, "w") as f:
    f.write(content)

try:
    os.replace(tmp_file, src_file)
    print(f"Atomic swap complete: {tmp_file} -> {src_file}")
except OSError as e:
    print(f"Atomic swap failed ({e}), falling back to copy/delete")
    shutil.copy2(tmp_file, src_file)
    os.remove(tmp_file)
    print(f"Fallback swap complete: {tmp_file} -> {src_file}")
