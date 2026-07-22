import asyncio
import os
import stat
from dumbledoer.dumbledoer_cli import execute_bash

async def test_permissions():
    result = await execute_bash("touch /workspace/test_perm.txt")
    print("Command Output:", result)
    
    file_path = "test_perm.txt"
    if os.path.exists(file_path):
        stat_info = os.stat(file_path)
        print(f"File UID: {stat_info.st_uid}")
        print(f"Host UID: {os.getuid()}")
        if stat_info.st_uid == os.getuid():
            print("SUCCESS: File is owned by the host user.")
        else:
            print("FAILURE: File is NOT owned by the host user.")
    else:
        print("FAILURE: File not found.")

if __name__ == "__main__":
    asyncio.run(test_permissions())
