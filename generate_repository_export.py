import os
import math
from pathlib import Path

# Configuration
OUTPUT_PREFIX = "repository_export"
MAX_FILES = 10
IDEAL_MAX_FILE_SIZE = 500 * 1024  # 500 KB target size before splitting

ALLOWED_EXTENSIONS = {
    '.py', '.sh', '.md', '.yml', '.yaml', '.txt', '.ini', '.json', '.csv',
    'Dockerfile', 'Makefile', 'requirements.txt', 'crontab.txt'
}
EXCLUDE_DIRS = {
    '.git', '.pytest_cache', '__pycache__', 'venv', 'env', 
    'openclaw_data/credentials', 'openclaw_data/sessions',
    'openclaw_data/workspace/.openclaw', 'node_modules'
}
EXCLUDE_EXTENSIONS = {
    '.pyc', '.log', '.sqlite', '.db', '.jpg', '.jpeg', '.png', '.gif', 
    '.bmp', '.webp', '.svg', '.pdf', '.zip', '.tar', '.gz', '.rar', 
    '.mp3', '.wav', '.aac', '.ogg', '.flac', '.env'
}

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
    
    # Get all entries, sorted: directories first, then files
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
    print("Scanning repository...")
    
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

    # 2. Determine target size per split file
    # Ensure it's bounded by IDEAL_MAX_FILE_SIZE unless we are forced to exceed it by the 10-file cap
    target_size_per_file = max(IDEAL_MAX_FILE_SIZE, math.ceil(total_size / MAX_FILES))
    
    # State variables for splitting
    file_index = 1
    current_out_file = None
    current_out_size = 0
    file_count = 0
    
    def open_next_file():
        nonlocal file_index, current_out_file, current_out_size
        if current_out_file:
            current_out_file.close()
            
        # Determine naming (e.g. repository_export_part1.txt)
        filename = f"{OUTPUT_PREFIX}_part{file_index}.txt"
        print(f"\n-> Opening {filename}...")
        
        current_out_file = open(filename, 'w', encoding='utf-8')
        current_out_file.write(f"# Repository Export: {root.resolve().name} (Part {file_index} of {MAX_FILES})\n")
        current_out_file.write(f"# Generated on: {os.popen('date').read().strip()}\n\n")
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
            
            # Read content
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # Format block
            file_header = f"### FILE: {rel_path}\n```{(path.suffix.lstrip('.') if path.suffix else '')}\n"
            file_footer = "\n```\n\n"
            full_block = file_header + content + ('' if content.endswith('\n') else '\n') + file_footer
            block_size = len(full_block)
            
            # Check if adding this file exceeds our size threshold AND we have room for more parts
            if (current_out_size + block_size > target_size_per_file) and (file_index < MAX_FILES) and (current_out_size > 0):
                file_index += 1
                out_f = open_next_file()
                out_f.write("## File Contents (Continued)\n\n")
            
            # Write to current file
            out_f.write(full_block)
            current_out_size += block_size
            file_count += 1
            print(f"Added: {rel_path} (to Part {file_index})")
            
        except Exception as e:
            print(f"Error reading '{path}': {e}")

    # Close the last open file
    if current_out_file:
        current_out_file.close()

    print(f"\nDone! Exported {file_count} files across {file_index} text file(s).")

if __name__ == "__main__":
    generate_repository_export()
    