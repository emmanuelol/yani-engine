import os
import sys

def patch_file(filepath):
    with open(filepath, "r") as f:
        content = f.read()

    old_block = """        if GUI_DIFF_ENABLED and has_code:
            print("Review proposed changes for the wave in VS Code.", file=sys.stderr)
            args = ["code", "--wait"] + wave_tmp_files
            await asyncio.to_thread(subprocess.run, args, check=False)
        else:"""

    new_block = """        if GUI_DIFF_ENABLED and has_code:
            print("Opening proposed changes in VS Code for review...", file=sys.stderr)
            for tmp_path in wave_tmp_files:
                basename = os.path.basename(tmp_path)
                actual_filename = basename.split("_", 1)[1] if "_" in basename else basename
                actual_filename = actual_filename.replace(".tmp", "").replace("__", "/")
                if os.path.exists(actual_filename):
                    args = ["code", "--diff", actual_filename, tmp_path]
                else:
                    args = ["code", tmp_path]
                await asyncio.to_thread(subprocess.run, args, check=False)
        
        # Always show terminal diff for fallback/quick review
        if True:"""

    if old_block in content:
        content = content.replace(old_block, new_block)
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Patched {filepath}")
    else:
        print(f"Warning: Could not find block to patch in {filepath}")

patch_file("/home/emmanuel/Documentos/GitHub/DumbleDoer/dumbledoer/dumbledoer_cli.py")
patch_file(os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py"))
