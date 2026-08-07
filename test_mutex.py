from dumbledoer.core.locks import get_registry_lock
from dumbledoer.core.orchestrator import get_registry_lock as orch_lock
from dumbledoer.core.state import get_registry_lock as state_lock
print(id(get_registry_lock()) == id(orch_lock()) == id(state_lock()))
