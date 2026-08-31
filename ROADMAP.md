# 🗺️ yani-engine Strategic Engineering Roadmap

## Vision
`yani-engine` is the enterprise-grade safety harness for autonomous AI coding agents, providing deterministic blast-radius containment, zero-trust sandbox execution, and observable multi-agent orchestration.

---

## 📍 Phase 1: Core Containment & Deterministic Execution (Current — v1.0.0)
- [x] **AST Blast-Radius Guardrails**: CodeGraph AST symbol call-tree indexing with a hard 20-symbol limit.
- [x] **Zero-Trust Docker Sandbox**: Git worktree isolation (`yani-base:latest`) preventing host environment corruption.
- [x] **Interactive Diff-Gate**: Shadow `.tmp` file validation with visual diff inspection and instant rollback.
- [x] **MultiLoopAsyncLock & AST DOM State**: Race-condition-free `memory.md` task registry.
- [x] **Persistent MCP Circuit Breakers**: Automatic isolation and probe-recovery for external MCP processes.
- [x] **OpenTelemetry Distributed Tracing**: Native span instrumentation for commands, waves, and vendor latencies.
- [x] **Deterministic Demo Generation**: VHS + Docker pipeline (`generate-demo` skill) for regression-proof video captures.
- [x] **Lite Pairing Fast-Path**: `yani-skill` convention scout with git co-change analysis.

---

## 📍 Phase 2: Enterprise Observability & Fleet Governance (Target — Q4 2026)
- [ ] **OTLP Visualizer Integration**: Pre-configured Grafana Tempo & Jaeger dashboards for agent execution traces.
- [ ] **Dynamic Policy Enforcement (`.yani/policy.rego`)**: OPA (Open Policy Agent) integration to enforce organization-specific code modification rules.
- [ ] **Multi-Model Cost Arbitrage**: Real-time pricing oracle switching sub-agent models based on live token budget thresholds.
- [ ] **Shadow CI Replay**: Replaying agent mutation waves against pull requests in headless CI pipelines.

---

## 📍 Phase 3: Distributed Multi-Agent Mesh (Target — 2027)
- [ ] **Cross-Repository Dependency Mesh**: Coordinated multi-repo refactoring with distributed AST impact graphs.
- [ ] **Remote Ephemeral Sandboxes (Kubernetes / Firecracker)**: Provisioning lightweight microVMs for massive parallel execution waves.
- [ ] **Cryptographic Proof of Containment**: Signed attestations of AST impact audits and Diff-Gate authorizations.

---

## 🤝 Contributing to the Roadmap
See [CONTRIBUTING.md](CONTRIBUTING.md) to propose feature additions or submit Architecture Decision Records (ADRs).
