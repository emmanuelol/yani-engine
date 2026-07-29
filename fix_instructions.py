import os
import subprocess

skills_dir = "skills"
commit = "c8ea3a1"

# Process in local repo
for root, dirs, files in os.walk(skills_dir):
    if "SKILL.md" in files:
        skill_name = os.path.basename(root)
        repo_path = f"skills/{skill_name}/SKILL.md"
        
        # Get original content
        result = subprocess.run(["git", "show", f"{commit}:{repo_path}"], capture_output=True, text=True)
        if result.returncode == 0:
            original_content = result.stdout
            
            # Write to INSTRUCTIONS.md in local repo
            with open(f"skills/{skill_name}/INSTRUCTIONS.md", "w") as f:
                f.write(original_content)
                
            # Write to INSTRUCTIONS.md in global plugin
            global_plugin_path = os.path.expanduser(f"~/.gemini/config/plugins/dumbledoer/skills/{skill_name}/INSTRUCTIONS.md")
            if os.path.exists(os.path.dirname(global_plugin_path)):
                with open(global_plugin_path, "w") as f:
                    f.write(original_content)
            
            print(f"Restored INSTRUCTIONS.md for {skill_name}")

# Now patch dumbledoer_cli.py
cli_paths = [
    "dumbledoer/dumbledoer_cli.py",
    os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py")
]

for path in cli_paths:
    if os.path.exists(path):
        with open(path, "r") as f:
            content = f.read()
            
        content = content.replace('os.path.join(self.plugin_root, "skills", command, "SKILL.md")', 'os.path.join(self.plugin_root, "skills", command, "INSTRUCTIONS.md")')
        
        with open(path, "w") as f:
            f.write(content)
        print(f"Patched {path}")

