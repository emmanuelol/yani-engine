import os
from pathlib import Path

# Configuration
OUTPUT_FILE = "repository_export.txt"
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
    print(f"Generating repository export to {OUTPUT_FILE}...")
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        # Header
        outfile.write(f"# Repository Export: {root.resolve().name}\n")
        outfile.write(f"# Generated on: {os.popen('date').read().strip()}\n\n")
        
        # 1. Directory Tree
        outfile.write("## Directory Structure\n\n```text\n")
        tree_lines = generate_tree(root)
        outfile.write(".\n" + "\n".join(tree_lines) + "\n```\n\n")
        
        # 2. File Contents
        outfile.write("## File Contents\n\n")
        
        file_count = 0
        for path in sorted(root.rglob('*')):
            if path.is_file() and is_text_file(path):
                try:
                    rel_path = path.relative_to('.')
                    outfile.write(f"### FILE: {rel_path}\n")
                    outfile.write("```" + (path.suffix.lstrip('.') if path.suffix else "") + "\n")
                    
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        outfile.write(content)
                        if not content.endswith('\n'):
                            outfile.write('\n')
                    
                    outfile.write("```\n\n")
                    file_count += 1
                    print(f"Added: {rel_path}")
                except Exception as e:
                    print(f"Error reading '{path}': {e}")

    print(f"\nDone! Exported {file_count} files to '{OUTPUT_FILE}'.")

if __name__ == "__main__":
    generate_repository_export()