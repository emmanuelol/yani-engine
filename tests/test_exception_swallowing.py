import pytest
import ast

def test_exception_swallowing():
    """Verify that the worker loop safely calls queue.task_done() even during crashes."""
    with open('dumbledoer/core/orchestrator.py', 'r') as f:
        tree = ast.parse(f.read())
        
    found_worker = False
    found_finally = False
    found_task_done = False
    
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'worker':
            found_worker = True
            for child in ast.walk(node):
                if isinstance(child, ast.Try):
                    if any(isinstance(f, ast.Expr) and getattr(f.value, 'func', None) and getattr(f.value.func, 'attr', None) == 'task_done' for f in child.finalbody):
                        found_finally = True
                        found_task_done = True
                        break
    
    assert found_worker, "Worker function not found."
    assert found_finally and found_task_done, "queue.task_done() must be in a finally block."
