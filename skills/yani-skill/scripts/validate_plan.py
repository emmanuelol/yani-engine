#!/usr/bin/env python3
import json, sys

def main():
    if len(sys.argv) < 2: return 1
    try:
        with open(sys.argv[1], 'r') as f: plan = json.load(f)
    except: return 1

    errors, seen = [], set()
    for i, t in enumerate(plan.get("tasks", [])):
        for field in ["id", "files_touched", "verification"]:
            if not t.get(field): errors.append(f"Tarea {t.get('id', i)}: falta '{field}'")
        for f in t.get("files_touched", []):
            if f in seen: errors.append(f"Solapamiento en '{f}'")
            seen.add(f)
        if not t.get("verification", {}).get("command"): errors.append("Falta comando de verificación")

    res = {"valid": len(errors) == 0, "errors": errors}
    print(json.dumps(res, indent=2))
    return 0 if res["valid"] else 1
if __name__ == "__main__": sys.exit(main())
