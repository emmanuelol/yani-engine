# Architecture and Diagrams

This document visually outlines the core structural components and protocols of the yani-engine architecture.

## 1. Core Decoupled Architecture

```mermaid
graph TD
    CLI[cli/main.py] -->|Hydrates| CFG[core/config.py]
    CLI -->|Dispatches| ORC[core/orchestrator.py]
    
    CFG -->|Injects Providers| ORC
    
    ORC -->|State Mutation| ST[core/state.py]
    ORC -->|Execution Waves| PL[core/planner.py]
    ORC -->|Tools & Sandbox| SB[core/sandbox.py]
    
    ORC -->|Provider Interface| LLM[core/llm_provider.py]
    LLM --> Gemini[GeminiProvider]
    LLM --> Local[LocalProvider]
    LLM --> Agy[AntigravityProvider]
```

## 2. Dynamic Vendor Tiering

yani-engine natively supports routing tasks to different LLM providers based on estimated effort. 

```mermaid
flowchart TD
    A[Task Dispatched] --> B{Estimated Effort}
    B -- Large --> C[Cloud Provider]
    B -- Medium/Small --> D[Local Provider]
    
    C --> E(Gemini / OpenAI Pro Models)
    D --> F(Ollama / vLLM Local Hardware)
    
    C -->|Fallback| G[Antigravity Native Session]
```

## 3. Session Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> Initialization
    
    Initialization --> Discovery
    note right of Initialization
        Loads /yani-engine start
        Initializes CodeGraph & Context7
    end note
    
    Discovery --> TaskPlanning
    note right of Discovery
        Ingests documentation
        Asks clarifying Q&A
    end note
    
    TaskPlanning --> PlanConfirmation
    note right of TaskPlanning
        Decomposes prompt into tasks
        Writes memory.md Task Registry
    end note
    
    PlanConfirmation --> ParallelExecutionWaves
    note right of PlanConfirmation
        User reviews and approves plan
    end note
    
    ParallelExecutionWaves --> GracefulShutdown : Budget Exhausted
    ParallelExecutionWaves --> Completion : Tasks Complete
    
    GracefulShutdown --> [*]
    Completion --> [*]
```

## 4. Task Execution & Checkpoint Protocol Sequence

```mermaid
sequenceDiagram
    autonumber
    actor ParentSession
    participant SubAgent
    participant CodeGraphMCP
    participant CheckpointManager
    participant Filesystem
    
    ParentSession->>SubAgent: Dispatch Task
    SubAgent->>CodeGraphMCP: Query AST / Call Graph
    CodeGraphMCP-->>SubAgent: Blast Radius (Impact)
    SubAgent->>SubAgent: Enforce <= 20 symbols limit
    SubAgent->>CheckpointManager: Pre-Write Snapshot
    CheckpointManager->>Filesystem: Write .bak to rollbacks/
    CheckpointManager-->>SubAgent: Rollback Generated
    SubAgent->>Filesystem: Write shadow .tmp for diff
    Filesystem-->>SubAgent: Diff-Gate ready
    SubAgent->>ParentSession: Awaiting Review
```

## 5. Sub-Agent Coordination & File Ownership Model

```mermaid
flowchart TD
    A[Pending Tasks] --> B{Dependency Graph Resolved?}
    B -- No --> C[Wait for Dependencies]
    B -- Yes --> D{Check File Ownership}
    
    D -- File Claimed by Another Task --> E[Queue for Next Wave]
    D -- No Overlap --> F{Import Coupling Analysis}
    
    F -- High Coupling --> E
    F -- Isolated --> G[Schedule in Current Wave]
    
    G --> H[Sub-Agent 1]
    G --> I[Sub-Agent 2]
    G --> J[Sub-Agent N]
    
    H --> K[Parallel Execution]
    I --> K
    J --> K
```

## 6. Knowledge Registry Evolution Flow

```mermaid
flowchart LR
    A[Session 1] -->|Records Insight| B(knowledge/entries/K-123.md)
    C[Session 2] -->|Records Decision| D(knowledge/entries/K-456.md)
    
    B --> E{OP-9 Sync: sync_knowledge.py}
    D --> E
    
    E --> F((knowledge/index.md))
    
    F -->|Injected via Semantic Memory| G[Session 3]
    F -->|Injected via Semantic Memory| H[Session N]
```

## 7. State Synchronization

### The Single-Writer Constraint
All state mutations to `memory.md` MUST route exclusively through `update_task_registry_row()` followed by `flush_task_registry()`. Direct writes via `TaskRegistryState` are deprecated and strictly forbidden. 

### Why this is enforced:
1. **Cache Integrity:** Parallel execution waves maintain an internal `_TASK_CACHE` to avoid deadlocking the I/O. Direct disk writes silently drift from this cache, causing wave workers to revert `completed` tasks back to `in_progress`.
2. **LLM Hallucination Prevention:** The LLM evaluates its own task success via `read_file("memory.md")`. Forcing an explicit `flush_task_registry()` ensures the LLM sees the absolute latest DOM state before deciding to retry a tool, preventing infinite QA iteration loops.

*See also:* [[Concurrency Safety]], [[Token Optimization Architecture]]
