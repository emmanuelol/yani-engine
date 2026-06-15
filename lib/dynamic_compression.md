# Sub-Agent Output Formatting (Dynamic Compression)

Gemini sub-agents must strictly follow these formatting rules for text outputs to save tokens and optimize the context window during execution.

## 1. Simple Tasks (Status checks, small validations)
- **Terseness Level**: Maximum.
- **Rule**: Drop articles (a/an/the), remove filler words, and use fragments.
- **Example**: "Task complete. Syntax ok."

## 2. Complex Tasks (Code changes, diagnostics)
- **Terseness Level**: Moderate.
- **Rule**: Drop filler words, but keep full sentence structures to accurately preserve technical nuance and reasoning.
- **Example**: "Memory leak found in database connection pool. Implemented automated timeout to resolve issue."

## 3. Persisted Artifacts & Planning
- **Terseness Level**: None (Normal prose).
- **Rule**: Anything written to disk (e.g., writing to `memory.md`, generating reports, updating docs) MUST be written in normal, uncompressed prose.

## 4. Absolute Invariants (CRITICAL)
- **Rule**: Code blocks, file paths, identifiers, URLs, and numeric values MUST NEVER be compressed, paraphrased, or abbreviated under any circumstances.
- **Requirement**: Always output these items exactly as intended.
