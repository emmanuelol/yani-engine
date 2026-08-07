import threading
import asyncio

_REGISTRY_LOCK = asyncio.Lock()
_MEMORY_MUTEX = asyncio.Lock()
_KNOWLEDGE_MUTEX = asyncio.Lock()

def get_registry_lock():
    return _REGISTRY_LOCK
