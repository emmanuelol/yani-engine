import os
import math
from pathlib import Path
from datetime import datetime

# Configuration
MAX_FILES = 10
IDEAL_MAX_FILE_SIZE = 500 * 1024  # 500 KB target size before splitting

ALLOWED_EXTENSIONS = {
    '.py', '.sh', '.md', '.yml', '.yaml', '.txt', '.ini', '.json', '.csv',
    'Dockerfile', 'Makefile', 'requirements.txt', 'crontab.txt', '.js', '.ts', 
    '.tsx', '.jsx', '.html', '.css', '.rs', '.go', '.java', '.cpp', '.h', '.c'
}

EXCLUDE_DIRS = {
    '.git', '.pytest_cache', '__pycache__', 'venv', 'env', '.venv',
    'openclaw_data/credentials', 'openclaw_data/sessions',
    'openclaw_data/workspace/.openclaw', 'node_modules', 'dist', 'build','.codegraph','.venv2',
    '.ruff_cache','.yani','test.lock','install.log',
}

EXCLUDE_EXTENSIONS = {
    '.pyc', '.log', '.sqlite', '.db', '.jpg', '.jpeg', '.png', '.gif', 
    '.bmp', '.webp', '.svg', '.pdf', '.zip', '.tar', '.gz', '.rar', 
    '.mp3', '.wav', '.aac', '.ogg', '.flac', '.env'
}

def get_repo_name() -> str:
    """Gets the sanitized name of the current directory."""
    raw_name = Path('.').resolve().name
    # Replace spaces and weird characters with underscores
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw_name)
    return safe_name

def is_ignored(path: Path) -> bool:
    """Check if a path should be ignored based on EXCLUDE_DIRS and EXCLUDE_EXTENSIONS."""
    # Check if any parent directory is in EXCLUDE_DIRS
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return True
    
    # Check specific paths (relative to root)
    rel_path = str(path.relative_to('.'))
    if any(rel_path.startswith(ex) for ex in EXCLUDE_DIRS):
        return True
        
    # Check extension
    if path.suffix.lower() in EXCLUDE_EXTENSIONS:
        return True
    
    return False

def is_text_file(path: Path) -> bool:
    """Determine if a file is a candidate for export."""
    if is_ignored(path):
        return False
    
    if path.suffix.lower() in ALLOWED_EXTENSIONS or path.name in ALLOWED_EXTENSIONS:
        return True
    
    return False

def generate_tree(root_dir: Path, prefix: str = "") -> list[str]:
    """Recursively generate a tree structure representation of the repository."""
    tree = []
    
    entries = sorted(
        [e for e in root_dir.iterdir() if not is_ignored(e)],
        key=lambda x: (not x.is_dir(), x.name.lower())
    )
    
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        tree.append(f"{prefix}{connector}{entry.name}")
        
        if entry.is_dir():
            new_prefix = prefix + ("    " if is_last else "│   ")
            tree.extend(generate_tree(entry, new_prefix))
            
    return tree

def generate_repository_export():
    root = Path('.')
    repo_name = get_repo_name()
    
    # --- NEW: Cleanup previous exports ---
    print("Checking for previous exports...")
    cleanup_count = 0
    # Look for files matching the output pattern in the root directory
    for old_export in root.glob(f"{repo_name}_part_*.txt"):
        try:
            old_export.unlink()
            cleanup_count += 1
        except Exception as e:
            print(f"Warning: Could not delete old export '{old_export.name}': {e}")
            
    if cleanup_count > 0:
        print(f"-> Removed {cleanup_count} previous export file(s) to avoid duplication.")
    # ------------------------------------

    print(f"\nScanning repository: {repo_name}...")
    
    # 1. Gather all files and calculate total size
    all_files = []
    total_size = 0
    
    for path in sorted(root.rglob('*')):
        if path.is_file() and is_text_file(path):
            all_files.append(path)
            total_size += path.stat().st_size
            
    if not all_files:
        print("No eligible files found to export.")
        return

    # 2. Determine target size and expected number of parts
    if total_size <= IDEAL_MAX_FILE_SIZE:
        expected_parts = 1
        target_size_per_file = total_size + 1024 # No splitting required
    else:
        # Calculate how many parts we'd need given the ideal size
        calculated_parts = math.ceil(total_size / IDEAL_MAX_FILE_SIZE)
        expected_parts = min(calculated_parts, MAX_FILES)
        # Recalculate target size to force it into the expected parts constraint
        target_size_per_file = math.ceil(total_size / expected_parts)
    
    # State variables
    file_index = 1
    current_out_file = None
    current_out_size = 0
    file_count = 0
    
    def open_next_file():
        nonlocal file_index, current_out_file, current_out_size
        if current_out_file:
            current_out_file.close()
            
        filename = f"{repo_name}_part_{file_index}_of_{expected_parts}.txt"
        print(f"\n-> Opening {filename}...")
        
        current_out_file = open(filename, 'w', encoding='utf-8')
        
        # Inject LLM-specific System Instructions
        current_out_file.write(f"--- REPOSITORY CONTEXT ---\n")
        current_out_file.write(f"Repository Name: {repo_name}\n")
        current_out_file.write(f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        current_out_file.write(f"Part: {file_index} of {expected_parts}\n")
        current_out_file.write(f"--------------------------\n\n")
        
        current_out_file.write("### SYSTEM INSTRUCTIONS FOR LLM ###\n")
        current_out_file.write(f"This document contains part {file_index} of {expected_parts} of the codebase for '{repo_name}'.\n")
        
        if expected_parts > 1:
            if file_index < expected_parts:
                current_out_file.write("ACTION REQUIRED: Acknowledge receipt of this part. DO NOT attempt to answer broad architectural questions yet. Wait until all parts are provided.\n")
            else:
                current_out_file.write("ACTION REQUIRED: This is the final part. You now have the complete codebase context. You may now answer user queries fully.\n")
        else:
            current_out_file.write("This document contains the entire codebase. You may answer user queries fully based on this context.\n")
        current_out_file.write("###################################\n\n")
        
        current_out_size = 0
        return current_out_file

    # Open first file
    out_f = open_next_file()
    
    # Write directory tree to the first file only
    print("Generating directory tree...")
    tree_content = "## Directory Structure\n\n```text\n.\n" + "\n".join(generate_tree(root)) + "\n```\n\n"
    out_f.write(tree_content)
    current_out_size += len(tree_content)
    
    out_f.write("## File Contents\n\n")
    
    # 3. Iterate and write files, splitting when necessary
    for path in all_files:
        try:
            rel_path = path.relative_to('.')
            file_ext = path.suffix.lstrip('.') if path.suffix else 'text'
            
            # Read content (use replace to avoid failing on slight decoding issues)
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                
            # Format block
            file_header = f"### FILE: {rel_path}\n```{file_ext}\n"
            file_footer = "\n```\n\n"
            full_block = file_header + content + ('' if content.endswith('\n') else '\n') + file_footer
            block_size = len(full_block)
            
            # Strict boundary check: only split if we have parts remaining
            if (current_out_size + block_size > target_size_per_file) and (file_index < expected_parts) and (current_out_size > 0):
                file_index += 1
                out_f = open_next_file()
                out_f.write("## File Contents (Continued)\n\n")
            
            out_f.write(full_block)
            current_out_size += block_size
            file_count += 1
            print(f"Added: {rel_path} (to Part {file_index})")
            
        except Exception as e:
            print(f"Error reading '{path}': {e}")

    if current_out_file:
        current_out_file.close()

    print(f"\nDone! Exported {file_count} files across {file_index} text file(s).")
    print(f"Prefix used: {repo_name}")

if __name__ == "__main__":
    generate_repository_export()