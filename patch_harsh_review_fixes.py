import os

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"Warning: File not found {filepath}")
        return

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    changes = 0

    # --- FIX 1: Missing Whitelist Tool ---
    if '"context7_query_docs"}' in content and '"context7_resolve_library_id"' not in content:
        content = content.replace(
            '"context7_query_docs"}', 
            '"context7_resolve_library_id", "context7_query_docs"}'
        )
        changes += 1

    # --- FIX 2: Net-New File Rejection Deletion ---
    old_rejection = """                    else:
                        console.print(f"[yellow]Rejected changes for {actual_filename} (no rollback found, file may be modified)[/yellow]")
                if task_id:"""
    
    new_rejection = """                    elif os.path.exists(target_path):
                        os.remove(target_path)
                        console.print(f"[yellow]Rejected new file creation, deleted {actual_filename}[/yellow]")
                if task_id:"""
    if old_rejection in content:
        content = content.replace(old_rejection, new_rejection)
        changes += 1

    # --- FIX 3: O4 Scanner Net-New Fix ---
    old_o4 = """                if bak_file and os.path.exists(target):
                    if filecmp.cmp(target, bak_file, shallow=False):
                        new_status = "rolled-back"
                    else:
                        new_status = "applied"
                    new_line = entry["line_text"].replace("| planned |", f"| {new_status} |")"""
                
    new_o4 = """                if bak_file:
                    if os.path.exists(target) and filecmp.cmp(target, bak_file, shallow=False):
                        new_status = "rolled-back"
                    else:
                        new_status = "applied"
                else:
                    if os.path.exists(target):
                        new_status = "applied"
                    else:
                        new_status = "rolled-back"
                new_line = entry["line_text"].replace("| planned |", f"| {new_status} |")"""
    if old_o4 in content:
        content = content.replace(old_o4, new_o4)
        changes += 1

    # --- FIX 4: Rollback Command Deletes Created Files ---
    old_rollback = """                for root, _, files in os.walk(bak_dir):
                    for file in files:
                        bak_path = os.path.join(root, file)
                        rel_path = bak_path.replace(bak_dir + "/", "").replace("__colon__", ":").replace("__", "/")
                        os.makedirs(os.path.dirname(os.path.abspath(rel_path)), exist_ok=True)
                        shutil.copy2(bak_path, rel_path)
                        print(f"Restored {rel_path}")
                await TaskRegistryState().update_task_status(task_id, "pending")"""

    new_rollback = """                # Find all files touched by this task in the Change Log
                touched_files = []
                try:
                    with open("memory.md", "r", encoding="utf-8") as f:
                        for line in f:
                            parts = [p.strip() for p in line.split("|")]
                            if len(parts) >= 6 and parts[2] == task_id:
                                touched_files.append(parts[3])
                except Exception:
                    pass

                restored_files = set()
                for root, _, files in os.walk(bak_dir):
                    for file in files:
                        bak_path = os.path.join(root, file)
                        rel_path = bak_path.replace(bak_dir + "/", "").replace("__colon__", ":").replace("__", "/")
                        os.makedirs(os.path.dirname(os.path.abspath(rel_path)), exist_ok=True)
                        shutil.copy2(bak_path, rel_path)
                        restored_files.add(rel_path)
                        print(f"Restored {rel_path}")
                
                # Delete files that were created by the task (no backup existed)
                for f_path in touched_files:
                    if f_path not in restored_files and os.path.exists(f_path):
                        os.remove(f_path)
                        print(f"Deleted newly created file {f_path}")
                        
                await TaskRegistryState().update_task_status(task_id, "pending")"""
    
    if old_rollback in content:
        content = content.replace(old_rollback, new_rollback)
        changes += 1

    if changes > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Applied {changes} structural fixes to {filepath}")

# Patch local repository
patch_file("dumbledoer/dumbledoer_cli.py")

# Patch global Antigravity installation
global_path = os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py")
patch_file(global_path)
