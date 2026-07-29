import os

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"Warning: File not found {filepath}")
        return

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # The exact marker we are looking for
    target = "## Section 5 — Recommended Next Steps"
    
    # Using safe string concatenation to avoid triple-quote CLI truncation
    insertion = (
        "## Section 4a — Theoretical Token Optimization\n"
        "Calculate the tokens saved during this session by DumbleDoer's dynamic tool filtering and sliced memory ingestion architecture.\n"
        "1. Estimate the total number of tool calls made across all completed tasks (assume an average of 5 tool calls per `small` task, 10 for `medium`, 20 for `large`).\n"
        "2. Multiply that total by `25,000` (the average input tokens saved per call by stripping unnecessary tools and truncating memory.md).\n"
        "3. Format as:\n\n"
        "```markdown\n"
        "## Token Optimization\n\n"
        "- Estimated Tool Calls Executed: {calculated_total}\n"
        "- Optimization Yield: ~{calculated_total * 25000} tokens saved\n"
        "- Engine Mechanism: Dynamic Tool Filtering & Sliced Memory Ingestion\n"
        "```\n\n"
        "---\n\n"
    )

    if "Theoretical Token Optimization" in content:
        print(f"⚠️ Already patched {filepath}")
        return

    if target in content:
        content = content.replace(target, insertion + target)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Successfully patched report instructions in {filepath}")
    else:
        print(f"⚠️ Could not find the target section in {filepath}.")

patch_file("skills/report/INSTRUCTIONS.md")
patch_file(os.path.expanduser("~/.gemini/config/plugins/dumbledoer/skills/report/INSTRUCTIONS.md"))