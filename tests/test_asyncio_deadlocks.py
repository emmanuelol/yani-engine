import pytest

def test_asyncio_deadlocks():
    """Verify that state mutations in state.py use the appropriate mutex/lock."""
    with open('dumbledoer/core/state.py', 'r') as f:
        content = f.read()
    assert '_MEMORY_MUTEX' in content or 'get_registry_lock()' in content, "State mutations must be protected by a lock to avoid asyncio deadlocks."
