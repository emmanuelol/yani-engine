import os
import glob
import re

def parse_frontmatter(content):
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}
    
    fm_text = match.group(1)
    data = {}
    for line in fm_text.splitlines():
        if ':' in line:
            key, val = line.split(':', 1)
            key = key.strip()
            val = val.strip()
            # simple list parsing for tags
            if val.startswith('[') and val.endswith(']'):
                val = [v.strip() for v in val[1:-1].split(',')]
            elif val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            data[key] = val
    return data

def main():
    entries_dir = "knowledge/entries"
    if not os.path.exists(entries_dir):
        print(f"Directory {entries_dir} not found.")
        return

    categories = {
        "decision": [],
        "success": [],
        "failure": [],
        "constraint": [],
        "insight": []
    }
    
    for file_path in glob.glob(os.path.join(entries_dir, "*.md")):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        fm = parse_frontmatter(content)
        if 'id' in fm and 'type' in fm:
            entry_type = fm['type'].lower()
            if entry_type in categories:
                categories[entry_type].append(fm)

    index_content = "# Knowledge Index\n\n"
    
    category_titles = {
        "decision": "Decisions",
        "success": "Successes",
        "failure": "Failures",
        "constraint": "Constraints",
        "insight": "Insights"
    }
    
    for c_key in ["decision", "success", "failure", "constraint", "insight"]:
        index_content += f"## {category_titles[c_key]}\n"
        index_content += "| ID | Title | Status | Created | Tags |\n"
        index_content += "|---|---|---|---|---|\n"
        
        # Sort by ID
        sorted_entries = sorted(categories[c_key], key=lambda x: x.get("id", ""))
        
        for entry in sorted_entries:
            e_id = entry.get("id", "")
            e_title = entry.get("title", "")
            e_status = entry.get("status", "")
            e_created = entry.get("created", "")
            e_tags = entry.get("tags", [])
            tags_str = ", ".join(e_tags) if isinstance(e_tags, list) else str(e_tags)
            
            index_content += f"| {e_id} | {e_title} | {e_status} | {e_created} | {tags_str} |\n"
            
        index_content += "\n"
        
    index_path = "knowledge/index.md"
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content.strip() + "\n")
        
    print(f"Successfully synced {index_path}")

if __name__ == "__main__":
    main()
