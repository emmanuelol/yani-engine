# Architecture and Diagrams

This document visually outlines the core structural components, concurrency models, and security protocols of the **yani-engine** architecture.

---

## 1. Core Decoupled Architecture

```mermaid
graph TD
    CLI["yani_engine/cli/main.py"] -->|"Hydrates"| CFG["yani_engine/core/config.py"]
    CLI -->|"Dispatches"| ORC["yani_engine/core/orchestrator.py"]
    
    CFG -->|"Injects Providers"| ORC
    
    ORC -->|"Multi-Loop Async Mutex"| LCK["yani_engine/core/locks.py"]
    ORC -->|"AST State Machine"| ST["yani_engine/core/state.py"]
    ORC -->|"Semantic Wave Planning"| PL["yani_engine/core/planner.py"]
    ORC -->|"Process-Isolated Sandbox"| SB["yani_engine/core/sandbox.py"]
    
    ORC -->|"MCP RPC Protocol"| MCP["CodeGraph & Context7 MCP Servers"]
    ORC -->|"Provider Interface"| LLM["yani_engine/core/llm_provider.py"]
    
    LLM --> Gemini["GeminiProvider"]
    LLM --> Local["LocalProvider (Ollama/vLLM)"]
    LLM --> Agy["AntigravityProvider"]
```

---

## 2. Dynamic Vendor Tiering (Brain vs. Hands)

yani-engine natively supports routing tasks to different LLM providers based on estimated effort. 

```mermaid
flowchart TD
    A["Task Dispatched"] --> B{"Estimated Effort"}
    B -- Large --> C["The Brain: Cloud Provider"]
    B -- Medium / Small --> D["The Hands: Local Hardware"]
    
    C --> E["Gemini 3.1 Pro / Heavy Models"]
    D --> F["Ollama / vLLM Local Endpoint"]
    
    C -->|"Fallback"| G["Antigravity Native Session Credits"]
```

---

## 3. Session Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> Initialization
    
    Initialization --> Discovery
    note right of Initialization
        Loads /yani-engine start
        Connects CodeGraph & Context7 MCP
    end note
    
    Discovery --> TaskPlanning
    note right of Discovery
        Ingests documentation
        Asks clarifying Q&A
    end note
    
    TaskPlanning --> PlanConfirmation
    note right of TaskPlanning
        Decomposes prompt into atomic tasks
        Writes memory.md Task Registry
    end note
    
    PlanConfirmation --> ParallelExecutionWaves
    note right of PlanConfirmation
        User reviews and approves plan
    end note
    
    ParallelExecutionWaves --> GracefulShutdown : Budget Threshold Reached (80%)
    ParallelExecutionWaves --> Completion : All Tasks Complete
    
    GracefulShutdown --> [*]
    Completion --> [*]
```

---

## 4. Task Execution & Fail-Closed Checkpoint Protocol

```mermaid
sequenceDiagram
    autonumber
    actor ParentSession as "Orchestrator Wave"
    participant SubAgent as "SubAgent Worker"
    participant CodeGraph as "CodeGraph MCP / CLI"
    participant Checkpoint as "CheckpointManager"
    participant Disk as "Filesystem (.yani/)"
    participant Review as "VS Code / Diff-Gate"

    ParentSession->>SubAgent: execute_task(task_id)
    SubAgent->>CodeGraph: codegraph impact <path> (5s timeout)
    alt Impact > 20 symbols OR Timeout
        CodeGraph-->>SubAgent: Blast Radius Exceeded / TimeoutExpired
        SubAgent-->>ParentSession: ❌ Reject Write (Fail-Closed)
    else Impact <= 20 symbols
        CodeGraph-->>SubAgent: Impact Approved
        SubAgent->>Checkpoint: write_rollback_copy(target, rollback_path)
        Checkpoint->>Disk: Copy original -> .yani/rollbacks/{task_id}/{encoded_path}
        SubAgent->>Disk: Stage new content -> .yani/tmp/{task_id}_{encoded_path}.tmp
        SubAgent->>Review: Diff-Gate: Compare .tmp vs .yani/rollbacks
        Review-->>ParentSession: User Approved -> atomic rename to target
    end
```

---

## 5. Sub-Agent Coordination & Semantic Dependency Model

```mermaid
flowchart TD
    A["Pending Tasks"] --> B{"Dependency Graph Resolved?"}
    B -- No --> C["Wait for Upstream Dependencies"]
    B -- Yes --> D{"Check Output File Claims"}
    
    D -- File Claimed in Active Wave --> E["Defer to Next Wave"]
    D -- No Direct Collision --> F{"CodeGraph Import Coupling"}
    
    F -- High Import Coupling --> E
    F -- Isolated Ast Graph --> G["Schedule in Current Wave"]
    
    G --> H["Worker 1"]
    G --> I["Worker 2"]
    G --> J["Worker N"]
    
    H --> K["Parallel Asyncio Execution"]
    I --> K
    J --> K
```

---

## 6. Knowledge Registry Evolution Flow

```mermaid
flowchart LR
    A["Session 1"] -->|"Records Insight"| B["knowledge/entries/K-001.md"]
    C["Session 2"] -->|"Records Decision"| D["knowledge/entries/K-002.md"]
    
    B --> E{"OP-9 Sync: sync_knowledge.py"}
    D --> E
    
    E --> F["knowledge/index.md"]
    
    F -->|"Injected via Semantic Memory"| G["Session 3"]
    F -->|"Injected via Semantic Memory"| H["Session N"]
```

---

## 7. State Synchronization & Multi-Loop Mutex Architecture

### The Single-Writer Constraint
All state mutations to `memory.md` MUST route exclusively through `update_task_registry_row()` followed by `flush_task_registry()`. Direct writes via raw file handles are deprecated and strictly forbidden.

### Concurrency Guarantees:
1. **`MultiLoopAsyncLock`**: Idempotent asyncio proxy preserving object memory addresses across imports (`id(get_registry_lock()) == id(orch_lock())`) while dynamically provisioning loop-safe `asyncio.Lock()` instances mapped to `id(asyncio.get_running_loop())`. Eliminates `RuntimeError: Event loop is closed` across multi-cycle test suites.
2. **Non-Blocking FileLock**: Synchronous `filelock.FileLock` operations are offloaded to worker threads via `asyncio.to_thread`, preventing 120-second filesystem lock waits from stalling the main event loop.
3. **AST DOM Manipulation**: The state machine utilizes `ASTMemoryMapper` (backed by `markdown-it-py`) to parse markdown tables into structural DOM representations, preserving arbitrary trailing columns and preventing race conditions.
