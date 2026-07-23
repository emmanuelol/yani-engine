#!/usr/bin/env bash

# 1. Ensure JSON commands utilize relative workspace pathing
find commands/ -name "*.json" -type f -exec sed -i 's|"~/.gemini/config/plugins/dumbledoer/run_dumbledoer.sh"|"./run_dumbledoer.sh"|g' {} +

# 2. Strict String replacement for artifact naming boundaries
find docs/ tests/ lib/ -type f -name "*.md" -exec python3 -c '
import sys
import os
for filepath in sys.argv[1:]:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Safe boundary replacements
    content = content.replace(".kandalf", ".dumbledoer")
    content = content.replace("/kandalf:", "/dumbledoer:")
    content = content.replace("kandalf/", "dumbledoer/")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
' {} +