#!/usr/bin/env python3
import subprocess, sys, json

def run(args): return subprocess.run(args, capture_output=True, text=True, check=True).stdout

def detect_base_branch():
    for c in ["main", "master", "develop", "trunk"]:
        if subprocess.run(["git", "rev-parse", "--verify", f"refs/heads/{c}"], capture_output=True).returncode == 0:
            return c
    return None

def main():
    args = sys.argv[1:]
    base_branch, expected_files = None, []
    
    if "--expect" in args:
        idx = args.index("--expect")
        expected_files = args[idx + 1:]
        args = args[:idx]

    if "--base" in args:
        idx = args.index("--base")
        if idx + 1 < len(args):
            base_branch = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            print(json.dumps({"valid": False, "error": "--base requiere un nombre de rama"})); return 1

    if len(args) < 1:
        print(json.dumps({"valid": False, "error": "Provee archivos en files_touched"})); return 1

    declared_files = set(args)
    try:
        current_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
        base_branch = base_branch or detect_base_branch()
        if not base_branch:
            print(json.dumps({"valid": False, "error": "No se pudo detectar rama base"})); return 1
        if current_branch == base_branch:
            print(json.dumps({"valid": False, "error": f"Estás en la rama base '{base_branch}'."})); return 1
        
        diff_output = run(["git", "diff", "--name-only", f"{base_branch}...HEAD"])
        actual_files = set(f for f in diff_output.split('\n') if f)
    except Exception as e:
        print(json.dumps({"valid": False, "error": str(e)})); return 1

    violations = actual_files - declared_files
    missing_expected = set(expected_files) - actual_files

    result = {"valid": len(violations) == 0 and len(missing_expected) == 0, "base_branch": base_branch, "current_branch": current_branch, "declared": sorted(declared_files), "actual": sorted(actual_files), "violations": sorted(violations), "missing_expected": sorted(missing_expected)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1
if __name__ == "__main__": sys.exit(main())
