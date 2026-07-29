import os

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"Warning: File not found {filepath}")
        return

    with open(filepath, "r") as f:
        content = f.read()

    old_session_creation = """    async def execute_task(self, task_id: str, description: str):
        print(f"Executing task {task_id}: {description}")
        chat_session = self.client.aio.chats.create(model=getattr(self, "model", "gemini-2.5-flash"), config={"tools": list(self.gemini_tools), "automatic_function_calling": {"disable": True}})"""

    new_session_creation = """    async def execute_task(self, task_id: str, description: str):
        print(f"Executing task {task_id}: {description}")
        
        # --- DYNAMIC MODEL TIERING ---
        effort = "small"
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                mem_content = f.read()
            import re
            match = re.search(rf"### {task_id}:.*?\n.*?- \*\*Estimated Effort\*\*: (small|medium|large)", mem_content, re.DOTALL)
            if match:
                effort = match.group(1).lower()
        except Exception:
            pass
            
        base_model = getattr(self, "model", "gemini-2.5-flash")
        
        # Upgrade to pro reasoning tier for complex execution waves
        if effort in ["medium", "large"] and "flash" in base_model:
            target_model = "gemini-2.5-pro"
            print(f"[Tier Upgrade] Task {task_id} requires {effort} effort. Spawning sub-agent on {target_model}.")
        else:
            target_model = base_model
            
        chat_session = self.client.aio.chats.create(model=target_model, config={"tools": list(self.gemini_tools), "automatic_function_calling": {"disable": True}})"""

    if old_session_creation in content:
        content = content.replace(old_session_creation, new_session_creation)
        with open(filepath, "w") as f:
            f.write(content)
        print(f"✅ Successfully patched dynamic tiering in {filepath}")
    else:
        print(f"⚠️ Could not find the execution block in {filepath}. It may already be patched.")

# Patch both local and global installations
patch_file("dumbledoer/dumbledoer_cli.py")
patch_file(os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py"))
