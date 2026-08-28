#!/usr/bin/env python3
import json, subprocess, sys
from collections import Counter

def run(args): return subprocess.run(args, capture_output=True, text=True, check=True).stdout

def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "falta el archivo"})); return 2
    target = sys.argv[1]
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 200
    min_ratio = float(sys.argv[sys.argv.index("--min-ratio") + 1]) if "--min-ratio" in sys.argv else 0.6
    at = sys.argv[sys.argv.index("--at") + 1] if "--at" in sys.argv else "HEAD"
    
    try: head = run(["git", "rev-parse", at]).strip()
    except: print(json.dumps({"error": f"revision desconocida: {at}"})); return 1

    cmd = f"git log --format=%H -n {limit} {head} -- {target}"
    try: shas = [s for s in run(["git", "log", "--format=%H", "-n", str(limit), head, "--", target]).split() if s]
    except subprocess.CalledProcessError as e:
        print(json.dumps({"error": f"git fallo: {e.stderr.strip()[:200]}"})); return 1

    if not shas:
        print(json.dumps({"target": target, "commits": 0, "computed_at_head": head, "coupled": [], "note": "sin historial"}))
        return 0

    counts = Counter()
    for sha in shas:
        for f in run(["git", "show", "--pretty=", "--name-only", sha]).splitlines():
            f = f.strip()
            if f and f != target: counts[f] += 1

    total = len(shas)
    coupled = [{"file": f, "co_commits": n, "of_total": total, "ratio": round(n / total, 4), "evidence": f"{n} de {total} commits que tocaron {target} tocaron tambien {f}"} 
               for f, n in counts.most_common() if n / total >= min_ratio]
    print(json.dumps({"target": target, "commits": total, "command": cmd, "computed_at_head": head, "min_ratio": min_ratio, "coupled": coupled}, ensure_ascii=False))
    return 0
if __name__ == "__main__": sys.exit(main())
