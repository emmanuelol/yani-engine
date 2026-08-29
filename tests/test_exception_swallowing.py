import pytest
import os
import ast

def test_exception_swallowing():
    """Verify that the worker loop safely calls queue.task_done() even during crashes.

    The worker was promoted from an inner closure in orchestrator.py to the
    _worker method on WaveExecutor in yani_engine/core/executor.py.
    This test verifies the same structural guarantee in its new home.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    target = os.path.join(repo_root, "yani_engine/core/executor.py")
    with open(target, "r") as f:
        tree = ast.parse(f.read())

    found_worker = False
    found_finally = False
    found_task_done = False

    for node in ast.walk(tree):
        # Worker was promoted to a method; accept either 'worker' or '_worker'
        if isinstance(node, ast.AsyncFunctionDef) and node.name in ("worker", "_worker"):
            found_worker = True
            for child in ast.walk(node):
                if isinstance(child, ast.Try):
                    if any(
                        isinstance(f, ast.Expr)
                        and getattr(f.value, "func", None) is not None
                        and getattr(f.value.func, "attr", None) == "task_done"
                        for f in child.finalbody
                    ):
                        found_finally = True
                        found_task_done = True
                        break

    assert found_worker, "Worker function not found in executor.py."
    assert found_finally and found_task_done, "queue.task_done() must be in a finally block."
