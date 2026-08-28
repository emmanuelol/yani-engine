import threading
import asyncio
from filelock import FileLock


class MultiLoopAsyncLock:
    """
    Idempotent asyncio.Lock proxy. Preserves object identity for callers 
    while multiplexing loop-safe locks to prevent 'Event loop is closed' errors.
    """
    def __init__(self):
        self._locks = {}
        self._dict_lock = threading.Lock()

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        with self._dict_lock:
            if loop_id not in self._locks:
                self._locks[loop_id] = asyncio.Lock()
            return self._locks[loop_id]

    async def acquire(self):
        return await self._get_lock().acquire()

    def release(self):
        self._get_lock().release()

    def locked(self):
        return self._get_lock().locked()

    async def __aenter__(self):
        return await self._get_lock().__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self._get_lock().__aexit__(exc_type, exc_val, exc_tb)


_REGISTRY_LOCK = MultiLoopAsyncLock()
_MEMORY_MUTEX = MultiLoopAsyncLock()
_KNOWLEDGE_MUTEX = MultiLoopAsyncLock()

# Cross-process file lock for memory.md synchronization
# Extended timeout to 120s to accommodate heavy execution waves
_FILE_LOCK = FileLock("memory.md.lock", timeout=120)

def get_registry_lock():
    return _REGISTRY_LOCK
