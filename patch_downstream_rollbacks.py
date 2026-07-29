import os
import sys

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"Warning: File not found {filepath}")
        return

    with open(filepath, "r") as f:
        content = f.read()

    changes_made = False

    # --- FIX 1: Diff Rejection Rollback Path ---
    old_rejection = """                # Find and restore from rollback backup
                import glob as _glob
                encoded_path = actual_filename.replace("/", "__")
                rollback_matches = _glob.glob(f".dumbledoer/rollbacks/*_{encoded_path}.bak")
                if rollback_matches:
                    os.replace(rollback_matches[0], target_path)
                    rollback_restored = True
                    console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")"""

    new_rejection = """                # Find and restore from rollback backup
                import glob as _glob
                encoded_path = actual_filename.replace("/", "__")
                possible_rollback = os.path.join(".dumbledoer", "rollbacks", task_id, encoded_path) if task_id else None
                
                if possible_rollback and os.path.exists(possible_rollback):
                    os.replace(possible_rollback, target_path)
                    rollback_restored = True
                    console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")
                else:
                    rollback_matches = _glob.glob(f".dumbledoer/rollbacks/*_{encoded_path}.bak")
                    if rollback_matches:
                        os.replace(rollback_matches[0], target_path)
                        rollback_restored = True
                        console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")"""

    # --- FIX 2: OrphanRecoveryScanner Parse Bug ---
    old_scanner_parse = """                            if len(parts) >= 7:
                                # | Timestamp | Checkpoint ID | Task ID | Target Path | Action | Status | Rationale |
                                change_log.append({
                                    "chk_id": parts[2],
                                    "target": parts[4],
                                    "status": parts[6],
                                    "line_text": line,
                                })"""

    new_scanner_parse = """                            if len(parts) >= 6:
                                # | Timestamp | Task ID | Target Path | Summary | Status | Rationale |
                                change_log.append({
                                    "chk_id": parts[2],
                                    "target": parts[3],
                                    "status": parts[5],
                                    "line_text": line,
                                })"""

    # --- FIX 3: OrphanRecoveryScanner O4 Fallback ---
    old_o4 = """            # O4: Evaluate planned Change Log entries and update memory.md
            new_content = content
            for chk_id, entry in planned_chks.items():
                target = entry["target"]
                bak_files = glob.glob(os.path.join(bak_dir, f"{chk_id}_*.bak"))
                if bak_files and os.path.exists(target):
                    bak_file = bak_files[0]
                    if filecmp.cmp(target, bak_file, shallow=False):"""

    new_o4 = """            # O4: Evaluate planned Change Log entries and update memory.md
            new_content = content
            for chk_id, entry in planned_chks.items():
                target = entry["target"]
                encoded_path = target.replace("/", "__")
                possible_rollback = os.path.join(bak_dir, chk_id, encoded_path)
                
                bak_file = None
                if os.path.exists(possible_rollback):
                    bak_file = possible_rollback
                else:
                    bak_files = glob.glob(os.path.join(bak_dir, f"{chk_id}_*.bak"))
                    if bak_files:
                        bak_file = bak_files[0]
                        
                if bak_file and os.path.exists(target):
                    if filecmp.cmp(target, bak_file, shallow=False):"""


    if old_rejection in content:
        content = content.replace(old_rejection, new_rejection)
        changes_made = True
    if old_scanner_parse in content:
        content = content.replace(old_scanner_parse, new_scanner_parse)
        changes_made = True
    if old_o4 in content:
        content = content.replace(old_o4, new_o4)
        changes_made = True

    if changes_made:
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Successfully patched {filepath}")
    else:
        print(f"No matching blocks found to patch in {filepath}. It may already be patched.")

# Patch local repository
patch_file("dumbledoer/dumbledoer_cli.py")

# Patch global Antigravity installation
global_path = os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py")
patch_file(global_path)
