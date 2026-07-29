import os
import sys

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"Warning: File not found {filepath}")
        return

    with open(filepath, "r") as f:
        content = f.read()

    changes_made = False

    # --- FIX 1: Resolve the SyntaxError in batch_diff_review ---
    old_rejection_syntax = """                    if rollback_matches:
                        os.replace(rollback_matches[0], target_path)
                        rollback_restored = True
                        console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")
                else:
                    console.print(f"[yellow]Rejected changes for {actual_filename} (no rollback found, file may be modified)[/yellow]")"""

    new_rejection_syntax = """                    if rollback_matches:
                        os.replace(rollback_matches[0], target_path)
                        rollback_restored = True
                        console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")
                    else:
                        console.print(f"[yellow]Rejected changes for {actual_filename} (no rollback found, file may be modified)[/yellow]")"""

    # --- FIX 2 & 3: Rebuild OrphanRecoveryScanner (O3 and O4 logic) ---
    old_scanner = """            valid_chks = {c["chk_id"] for c in change_log}
            planned_chks = {c["chk_id"]: c for c in change_log if c["status"] == "planned"}
            
            # O3: Discard orphaned .json checkpoints
            for chk_file in glob.glob(os.path.join(chk_dir, "*.json")):
                basename = os.path.basename(chk_file)
                chk_id = basename.replace(".json", "")
                if chk_id not in valid_chks:
                    os.remove(chk_file)
                    console.print(f"[yellow]O3: Discarded orphaned checkpoint {chk_file}[/yellow]")
                    
            # O5: Discard orphaned .bak rollbacks
            for bak_file in glob.glob(os.path.join(bak_dir, "*.bak")):
                basename = os.path.basename(bak_file)
                chk_id = basename.split("_")[0] if "_" in basename else basename.replace(".bak", "")
                if chk_id not in valid_chks:
                    os.remove(bak_file)
                    console.print(f"[yellow]O5: Discarded orphaned rollback {bak_file}[/yellow]")
                    
            # O4: Evaluate planned Change Log entries and update memory.md
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

    new_scanner = """            # Build valid checkpoints explicitly from Checkpoint Registry
            valid_checkpoints = set()
            try:
                start_idx, end_idx = ASTMemoryMapper.locate_heading_block(content, "##", "Checkpoint Registry")
                if start_idx != -1:
                    for line in content.splitlines()[start_idx+1:end_idx]:
                        if line.strip().startswith("|") and "---" not in line and "Checkpoint ID" not in line:
                            parts = [p.strip() for p in line.split("|")]
                            if len(parts) >= 2:
                                valid_checkpoints.add(parts[1]) # Checkpoint ID is parts[1]
            except Exception:
                pass

            # Use a list to prevent dictionary key collisions on multi-file tasks
            planned_chks = [c for c in change_log if c["status"] == "planned"]
            
            # O3: Discard orphaned .json checkpoints safely
            for chk_file in glob.glob(os.path.join(chk_dir, "*.json")):
                basename = os.path.basename(chk_file)
                chk_id = basename.replace(".json", "")
                if chk_id not in valid_checkpoints:
                    os.remove(chk_file)
                    console.print(f"[yellow]O3: Discarded orphaned checkpoint {chk_file}[/yellow]")
                    
            # O4: Evaluate planned Change Log entries and update memory.md
            new_content = content
            for entry in planned_chks:
                task_id = entry["chk_id"]
                target = entry["target"]
                encoded_path = target.replace("/", "__")
                possible_rollback = os.path.join(bak_dir, task_id, encoded_path)
                
                bak_file = None
                if os.path.exists(possible_rollback):
                    bak_file = possible_rollback
                else:
                    bak_files = glob.glob(os.path.join(bak_dir, f"*_{encoded_path}.bak"))
                    if bak_files:
                        bak_file = bak_files[0]
                        
                if bak_file and os.path.exists(target):
                    if filecmp.cmp(target, bak_file, shallow=False):"""

    if old_rejection_syntax in content:
        content = content.replace(old_rejection_syntax, new_rejection_syntax)
        changes_made = True
    if old_scanner in content:
        content = content.replace(old_scanner, new_scanner)
        changes_made = True

    if changes_made:
        with open(filepath, "w") as f:
            f.write(content)
        print(f"✅ Successfully patched {filepath}")
    else:
        print(f"⚠️ No matching blocks found to patch in {filepath}.")

# Patch local repository
patch_file("dumbledoer/dumbledoer_cli.py")

# Patch global Antigravity installation
global_path = os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py")
patch_file(global_path)
