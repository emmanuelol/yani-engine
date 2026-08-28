import os
import glob
import shutil
import subprocess

def purge_system():
    print("🧹 Initiating OOM Debris Purge...")

    # 1. Nuke Orphaned Docker Containers
    print("🐳 Scanning for dangling Docker containers...")
    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "-q", "-f", "name=yani_engine-sandbox-"], 
            capture_output=True, text=True
        )
        container_ids = res.stdout.strip().splitlines()
        
        if container_ids:
            print(f"   Found {len(container_ids)} ghost containers. Terminating...")
            for cid in container_ids:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
            print("   ✅ Containers destroyed. RAM freed.")
        else:
            print("   ✅ No ghost containers found.")
    except Exception as e:
        print(f"   ⚠️ Docker cleanup failed: {e}")

    # 2. Eradicate Shadow Clones
    print("📁 Scanning for bloated shadow directories...")
    shadow_dirs = glob.glob(".yani_engine/shadow_*")
    if shadow_dirs:
        print(f"   Found {len(shadow_dirs)} shadow clones. Deleting...")
        for shadow_dir in shadow_dirs:
            try:
                shutil.rmtree(shadow_dir, ignore_errors=True)
            except Exception as e:
                print(f"   ⚠️ Failed to delete {shadow_dir}: {e}")
        print("   ✅ Shadow clones eradicated. Disk cache cleared.")
    else:
        print("   ✅ No shadow clones found.")

    # 3. Sweep Stale Tmp Files
    print("📄 Sweeping stale .tmp files...")
    tmp_files = glob.glob(".yani_engine/tmp/*.tmp")
    if tmp_files:
        for tmp in tmp_files:
            try:
                os.remove(tmp)
            except Exception:
                pass
        print(f"   ✅ Swept {len(tmp_files)} stale tmp files.")
    else:
        print("   ✅ No stale tmp files found.")

    print("\n🚀 System purge complete. Your environment is clean.")

if __name__ == "__main__":
    purge_system()
