# 🤝 Contributing to yani-engine

Thank you for contributing to `yani-engine`! We welcome contributions that improve safety, performance, and deterministic containment for autonomous AI coding agents.

---

## 🏛️ Guiding Architectural Principles

Every contribution must adhere to our core tenets:
1. **Containment Over Capability**: An agent with bounded blast radius is superior to an unbounded agent with infinite agency.
2. **Fail-Closed by Default**: If an AST graph indexer, MCP connection, or token budget fails or times out, the engine **must reject** the mutation.
3. **No Unchecked State Mutations**: All changes to `memory.md` must pass through Pydantic bouncers and `MultiLoopAsyncLock`.
4. **Deterministic Testing**: Every feature must include automated regression tests in `tests/`.

---

## 🛠️ Development Setup

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/emmanuelol/yani-engine.git
   cd yani-engine
   ```

2. **Set up Virtual Environment with `uv`:**
   ```bash
   uv venv .venv
   source .venv/bin/activate
   uv pip install -r requirements.txt
   uv pip install pytest pytest-asyncio
   ```

3. **Build the Sandbox Base Image:**
   ```bash
   docker build -t yani-base:latest .
   ```

---

## 🧪 Testing Protocol

Run the full deterministic test suite:
```bash
pytest tests/ -q
```

All 63+ tests must pass with zero failures.

### Test Categories
* `tests/test_state_integrity.py`: Task registry CRUD & Pydantic bouncers.
* `tests/test_mcp_circuit.py`: Circuit breaker state transitions (CLOSED -> OPEN -> HALF-OPEN).
* `tests/test_token_bleed.py`: Error envelope truncation guardrails.
* `tests/test_diff_gate_ui.py`: Shadow `.tmp` file rollback & approval gates.
* `tests/test_asyncio_deadlocks.py`: Event loop lock safety.

---

## 📐 Proposing Architectural Changes

For major changes affecting data flow, memory schemas, or sandbox boundaries:
1. Submit an **Architecture Decision Record (ADR)** in `docs/adrs/` following the format in [`docs/adrs/ADR-001-memory-md-over-sqlite.md`](docs/adrs/ADR-001-memory-md-over-sqlite.md).
2. Open a Pull Request referencing the ADR.
3. Ensure CI passes and no AST blast-radius assumptions are broken.

---

## 📄 License
By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
