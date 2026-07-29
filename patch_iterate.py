import json
import os

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    with open(filepath, "r") as f:
        data = json.load(f)

    if "options" in data:
        del data["options"]

    if "execute" in data and "args" in data["execute"]:
        data["execute"]["args"] = ["iterate"]

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Patched {filepath}")

patch_file("/home/emmanuel/Documentos/GitHub/DumbleDoer/commands/iterate.json")
patch_file(os.path.expanduser("~/.gemini/config/plugins/dumbledoer/commands/iterate.json"))
