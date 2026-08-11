import threading
import asyncio
from filelock import FileLock

_REGISTRY_LOCK = asyncio.Lock()
_MEMORY_MUTEX = asyncio.Lock()
_KNOWLEDGE_MUTEX = asyncio.Lock()

# Cross-process file lock for memory.md synchronization
# Extended timeout to 120s to accommodate heavy execution waves
_FILE_LOCK = FileLock("memory.md.lock", timeout=120)

def get_registry_lock():
    return _REGISTRY_LOCK
