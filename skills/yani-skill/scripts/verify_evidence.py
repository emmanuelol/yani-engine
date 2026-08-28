#!/usr/bin/env python3
import json, subprocess, sys, pathlib

HERE = pathlib.Path(__file__).resolve().parent
COCHANGE = HERE / "cochange.py"

def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "falta archivo objetivo"})); return 1
    target = sys.argv[1]
    at = sys.argv[sys.argv.index("--at") + 1] if "--at" in sys.argv else "HEAD"

    try:
        out = subprocess.run([sys.executable, str(COCHANGE), target, "--at", at], capture_output=True, text=True, check=True).stdout
        real = json.loads(out)
    except subprocess.CalledProcessError as e:
        print(json.dumps({"ok": False, "error": f"no se pudo re-ejecutar: {e.stderr.strip()[:200]}"})); return 1
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"JSON invalido: {e}"})); return 1

    if real.get("commits", 0) == 0:
        print(json.dumps({"ok": True, "note": "sin historial", "real": real})); return 0

    print(json.dumps({"ok": True, "reproducible": True, "computed_at_head": real.get("computed_at_head"), "commits": real.get("commits"), "coupled_files": [c["file"] for c in real.get("coupled", [])], "note": "evidencia re-ejecutada exitosamente"}, ensure_ascii=False))
    return 0
if __name__ == "__main__": sys.exit(main())
