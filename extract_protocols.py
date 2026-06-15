import glob
import os

files = glob.glob("konfio_opentelemetry_full_code_part_*.txt")
for filepath in files:
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    out_f = None
    for line in lines:
        if line.startswith("📂 FILE: "):
            if out_f:
                out_f.close()
            target_path = line.replace("📂 FILE: ", "").strip()
            if target_path.startswith("./"):
                target_path = target_path[2:]
            
            if target_path.startswith("lib/") or target_path.startswith("skills/"):
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                out_f = open(target_path, "w", encoding="utf-8")
            else:
                out_f = None
            continue
            
        if line.startswith("=============================="):
            continue
            
        if out_f:
            # Complete agy (Antigravity/Gemini) adaptation
            adapted_line = line
            adapted_line = adapted_line.replace("Kandalf", "DumbleDoer").replace("kandalf", "dumbledoer")
            adapted_line = adapted_line.replace("CLAUDE.md", "SYSTEM_INSTRUCTIONS.md")
            adapted_line = adapted_line.replace(".claude", ".dumbledoer")
            adapted_line = adapted_line.replace("claude", "agy")
            adapted_line = adapted_line.replace("Claude", "Gemini")
            adapted_line = adapted_line.replace("sonnet", "gemini-2.0-flash")
            adapted_line = adapted_line.replace("opus", "gemini-2.0-pro")
            out_f.write(adapted_line)
            
    if out_f:
        out_f.close()

print("Extraction and complete agy adaptation successful.")
