# Backward-compatibility shim for legacy imports and test suites
import sys
import warnings
import yani_engine
from yani_engine import core, cli
import yani_engine.core.locks
import yani_engine.core.state
import yani_engine.core.config
import yani_engine.core.orchestrator
import yani_engine.core.planner
import yani_engine.core.sandbox
import yani_engine.core.llm_provider
import yani_engine.cli.main

sys.modules["dumbledoer.core"] = yani_engine.core
sys.modules["dumbledoer.cli"] = yani_engine.cli
sys.modules["dumbledoer.core.locks"] = yani_engine.core.locks
sys.modules["dumbledoer.core.state"] = yani_engine.core.state
sys.modules["dumbledoer.core.config"] = yani_engine.core.config
sys.modules["dumbledoer.core.orchestrator"] = yani_engine.core.orchestrator
sys.modules["dumbledoer.core.planner"] = yani_engine.core.planner
sys.modules["dumbledoer.core.sandbox"] = yani_engine.core.sandbox
sys.modules["dumbledoer.core.llm_provider"] = yani_engine.core.llm_provider
sys.modules["dumbledoer.cli.main"] = yani_engine.cli.main

warnings.warn(
    "The 'dumbledoer' package namespace is deprecated. Please use 'yani_engine' instead.",
    DeprecationWarning,
    stacklevel=2
)
