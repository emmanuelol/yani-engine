import os
import concurrent.futures
import pytest
import dumbledoer.dumbledoer_cli as cli
from filelock import FileLock

@pytest.fixture
def mock_file_ops(tmp_path, monkeypatch):
    test_memory = tmp_path / "memory.md"
    
    def mock_read(path):
        if path == "memory.md":
            return test_memory.read_text() if test_memory.exists() else "Error"
        return "Error"
        
    def mock_write(path, content):
        if path == "memory.md":
            test_memory.write_text(content)
            return "Success"
        return "Error"
        
    monkeypatch.setattr(cli, "read_file", mock_read)
    monkeypatch.setattr(cli, "_write_file", mock_write)
    monkeypatch.setattr(cli.PlanValidator, "validate", lambda x: "OK")
    return test_memory

def test_concurrent_state_writes(mock_file_ops):
    
    def append_to_registry(i):
        with cli.REGISTRY_LOCK:
            current = cli.read_file("memory.md")
            if current.startswith("Error"):
                current = ""
            new_content = current + f"Entry {i}\n"
            cli.update_memory_registry(new_content)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(append_to_registry, i) for i in range(20)]
        concurrent.futures.wait(futures)

    final_content = mock_file_ops.read_text()
    
    for i in range(20):
        assert f"Entry {i}\n" in final_content, f"Entry {i} missing from final content!"
