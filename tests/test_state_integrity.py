import os
import concurrent.futures
from filelock import FileLock
from dumbledoer.dumbledoer_cli import update_memory_registry, read_file, REGISTRY_LOCK

def append_to_registry(i):
    # Read-modify-write cycle using the same lock instance
    with REGISTRY_LOCK:
        current = read_file("memory.md")
        if current.startswith("Error"):
            current = ""
        new_content = current + f"Entry {i}\n"
        update_memory_registry(new_content)

def test_concurrent_state_writes():
    if os.path.exists("memory.md"):
        os.remove("memory.md")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(append_to_registry, i) for i in range(20)]
        concurrent.futures.wait(futures)

    final_content = read_file("memory.md")
    
    for i in range(20):
        assert f"Entry {i}\n" in final_content, f"Entry {i} missing from final content!"

    if os.path.exists("memory.md"):
        os.remove("memory.md")
    if os.path.exists("memory.md.lock"):
        os.remove("memory.md.lock")
