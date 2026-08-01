import os
import glob

# Scrub everything before the first YAML frontmatter (---) in all INSTRUCTIONS.md files
for filepath in glob.glob("skills/*/INSTRUCTIONS.md"):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    with open(filepath, "w", encoding="utf-8") as f:
        skip = True
        for line in lines:
            if line.startswith("---"):
                skip = False
            if not skip:
                f.write(line)
                
    print(f"Purged inception headers from {filepath}")
