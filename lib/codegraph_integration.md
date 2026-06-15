# CodeGraph Integration Protocol

A mandatory 10-step data flow requiring impact analysis before any file modification. This ensures safe codebase transformations.

## The 10-Step Data Flow

1. **Identify Target**: Agent identifies the file or symbol it intends to modify.
2. **Query CodeGraph**: Issue a structural query to the `@colbymchenry/codegraph` MCP server for the target symbol or file.
3. **Parse Dependencies**: Analyze the upstream and downstream dependencies returned by CodeGraph.
4. **Calculate Impact Radius**: Count the total number of symbols/files affected directly or indirectly by the proposed change.
5. **Threshold Check**: If the blast radius exceeds **20 symbols**, the agent must **HALT** execution immediately.
6. **Report Radius**: Log the calculated radius to the console and update the `memory.md` session log.
7. **Request Confirmation (Optional)**: If near the threshold or uncertain, prompt the user for confirmation.
8. **Draft Change Plan**: Formulate the exact file modifications, ensuring all dependent symbols are accounted for.
9. **Execute Checkpoint Protocol**: Proceed with the 6-step Checkpoint Protocol for the proposed changes.
10. **Update CodeGraph**: After successful application, trigger a CodeGraph re-index to update the codebase structure.
