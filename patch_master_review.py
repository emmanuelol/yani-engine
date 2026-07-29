import os
import sys

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"Warning: File not found {filepath}")
        return

    with open(filepath, "r") as f:
        content = f.read()

    changes_made = False

    # --- FIX 1: Initialize budget_manager in __init__ & clean dead code ---
    old_init = """        self.local_tools = [read_file, read_code_block, write_file_with_review, execute_bash, update_memory_registry, run_rtk, add_task, record_knowledge]
        self.gemini_tools = list(self.local_tools)"""

    new_init = """        self.local_tools = [read_file, read_code_block, write_file_with_review, execute_bash, update_memory_registry, run_rtk, add_task, record_knowledge]
        self.gemini_tools = list(self.local_tools)
        try:
            with get_registry_lock():
                with open("memory.md", "r", encoding="utf-8") as f:
                    self.budget_manager = BudgetManager(f.read())
        except Exception:
            self.budget_manager = BudgetManager("")"""

    old_get_tools = """    def _get_tools_for_command(self, command: str):
        allowed = self.COMMAND_TOOL_WHITELIST.get(command)
        if not allowed:
            return self.gemini_tools
        return [t for t in self.gemini_tools if getattr(t, "__name__", "") in allowed]
        
        # Initialize BudgetManager
        try:
            with get_registry_lock():
                with open("memory.md", "r", encoding="utf-8") as f:
                    self.budget_manager = BudgetManager(f.read())
        except Exception:
            self.budget_manager = BudgetManager("")"""

    new_get_tools = """    def _get_tools_for_command(self, command: str):
        allowed = self.COMMAND_TOOL_WHITELIST.get(command)
        if not allowed:
            return self.gemini_tools
        return [t for t in self.gemini_tools if getattr(t, "__name__", "") in allowed]"""

    # --- FIX 2: Preserve Rollback Backups via shutil.copy2 on Rejection ---
    old_rejection_copy = """                if possible_rollback and os.path.exists(possible_rollback):
                    os.replace(possible_rollback, target_path)
                    rollback_restored = True
                    console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")
                else:
                    rollback_matches = _glob.glob(f".dumbledoer/rollbacks/*_{encoded_path}.bak")
                    if rollback_matches:
                        os.replace(rollback_matches[0], target_path)
                        rollback_restored = True
                        console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")"""

    new_rejection_copy = """                if possible_rollback and os.path.exists(possible_rollback):
                    shutil.copy2(possible_rollback, target_path)
                    rollback_restored = True
                    console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")
                else:
                    rollback_matches = _glob.glob(f".dumbledoer/rollbacks/*_{encoded_path}.bak")
                    if rollback_matches:
                        shutil.copy2(rollback_matches[0], target_path)
                        rollback_restored = True
                        console.print(f"[yellow]Rejected and rolled back changes for {actual_filename}[/yellow]")"""

    # --- FIX 3: Add os.makedirs Safety Guard in Standalone Rollback ---
    old_standalone_rollback = """                for root, _, files in os.walk(bak_dir):
                    for file in files:
                        bak_path = os.path.join(root, file)
                        rel_path = bak_path.replace(bak_dir + "/", "").replace("__colon__", ":").replace("__", "/")
                        os.replace(bak_path, rel_path)
                        print(f"Restored {rel_path}")"""

    new_standalone_rollback = """                for root, _, files in os.walk(bak_dir):
                    for file in files:
                        bak_path = os.path.join(root, file)
                        rel_path = bak_path.replace(bak_dir + "/", "").replace("__colon__", ":").replace("__", "/")
                        os.makedirs(os.path.dirname(os.path.abspath(rel_path)), exist_ok=True)
                        shutil.copy2(bak_path, rel_path)
                        print(f"Restored {rel_path}")"""

    if old_init in content:
        content = content.replace(old_init, new_init)
        changes_made = True
    if old_get_tools in content:
        content = content.replace(old_get_tools, new_get_tools)
        changes_made = True
    if old_rejection_copy in content:
        content = content.replace(old_rejection_copy, new_rejection_copy)
        changes_made = True
    if old_standalone_rollback in content:
        content = content.replace(old_standalone_rollback, new_standalone_rollback)
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
