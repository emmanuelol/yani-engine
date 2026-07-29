import os
import re

skills = ["start", "execute", "resume", "report", "rollback", "update-docs", "audit", "iterate", "status"]
other_skills = ["caveman", "obsidian-markdown"]

DELEGATION_DIRECTIVE = """> [!IMPORTANT] STRICT DELEGATION DIRECTIVE
> You are the user-facing interface, NOT the orchestrator. 
> You are STRICTLY FORBIDDEN from using `Edit`, `Create`, or `Replace` tools to fulfill this command.
> You MUST execute the following exact bash command using your `Bash` tool:
> `bash ~/.gemini/config/plugins/dumbledoer/run_dumbledoer.sh {skill}`
> Wait for the bash script to complete, and relay its output to the user. Do nothing else.

"""

def fix_skill(skill_path, skill_name, is_other=False):
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the YAML frontmatter
    match = re.search(r"---\nname:.*?\n---", content, re.DOTALL)
    if not match:
        print(f"Could not find frontmatter for {skill_name}")
        return

    frontmatter = match.group(0) + "\n\n"
    
    if not is_other:
        # Replace the entire file with just the frontmatter and the strict delegation directive
        new_content = frontmatter + DELEGATION_DIRECTIVE.format(skill=skill_name)
    else:
        # For other skills, put the frontmatter at the top, followed by whatever was before it, and then whatever was after it
        before = content[:match.start()].strip()
        after = content[match.end():].strip()
        
        new_content = frontmatter
        if before:
            new_content += before + "\n\n"
        if after:
            new_content += after + "\n"

    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Fixed {skill_name}")

for skill in skills:
    path = f"skills/{skill}/SKILL.md"
    if os.path.exists(path):
        fix_skill(path, skill)
    else:
        print(f"Skill {skill} not found at {path}")

for skill in other_skills:
    path = f"skills/{skill}/SKILL.md"
    if os.path.exists(path):
        fix_skill(path, skill, is_other=True)
    else:
        print(f"Skill {skill} not found at {path}")
