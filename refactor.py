import os
import glob
import json

# Objective 1: Relative Pathing in JSON Commands
commands_dir = "commands"
if os.path.exists(commands_dir):
    for json_file in glob.glob(os.path.join(commands_dir, "*.json")):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = f.read()
        
        new_data = data.replace('"~/.gemini/config/plugins/dumbledoer/run_dumbledoer.sh"', '"./run_dumbledoer.sh"')
        
        if data != new_data:
            with open(json_file, 'w', encoding='utf-8') as f:
                f.write(new_data)
            print(f"Updated {json_file}")

# Objective 2: Purge "Kandalf" Ghost Strings
dirs_to_traverse = ["tests", "docs"]
for d in dirs_to_traverse:
    if os.path.exists(d):
        for root, _, files in os.walk(d):
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                except (UnicodeDecodeError, IsADirectoryError):
                    continue
                
                new_content = content.replace(".kandalf", ".dumbledoer").replace("/kandalf:", "/dumbledoer:")
                if content != new_content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"Refactored {filepath}")
