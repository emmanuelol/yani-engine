# hero-demo.tape — yani-engine core value proposition demo
# Renders: blast radius detection → fail-closed block → atomic wave decomposition → Diff-Gate
#
# Usage: vhs hero-demo.tape
# Output: yani-engine-demo.gif

Output yani-engine-demo.gif
Set FontSize 22
Set Width 1200
Set Height 800
Set Theme "Dracula"
Set TypingSpeed 80ms

# --- Scene 1: Start the engine ---
Type "yani-engine execute 'Refactor auth module to use OAuth2'"
Enter
Sleep 2s

# --- Scene 2: CodeGraph analysis ---
Type "# ── yani-engine ──────────────────────────────────"
Enter
Sleep 500ms
Type "echo '🔍 Querying CodeGraph for blast radius...'"
Enter
Sleep 1.5s

Type "echo '   Analyzing: auth.py → session.py → middleware.py → api.py'"
Enter
Sleep 500ms
Type "echo '   Symbols affected: 42 functions, 18 classes, 7 modules'"
Enter
Sleep 1s

# --- Scene 3: Blast radius exceeded — fail-closed ---
Type "echo ''"
Enter
Type "echo '❌ BLAST RADIUS EXCEEDED'"
Enter
Sleep 500ms
Type "echo '   Threshold: 20 symbols   |   Detected: 42 symbols'"
Enter
Type "echo '   🛡️  Fail-Closed: Dangerous mutation BLOCKED.'"
Enter
Sleep 2s

# --- Scene 4: Atomic wave decomposition ---
Type "echo ''"
Enter
Type "echo '🔄 Decomposing into safer, atomic waves...'"
Enter
Sleep 1s

Type "echo '   ✅ T-001: Extract OAuth2 config schema        [small]  wave-1'"
Enter
Sleep 300ms
Type "echo '   ✅ T-002: Add OAuth2 token provider           [medium] wave-1'"
Enter
Sleep 300ms
Type "echo '   ✅ T-003: Migrate session.py to new provider  [medium] wave-2'"
Enter
Sleep 300ms
Type "echo '   ✅ T-004: Update middleware auth checks        [small]  wave-2'"
Enter
Sleep 300ms
Type "echo '   ✅ T-005: Update API endpoint auth decorators  [small]  wave-3'"
Enter
Sleep 300ms
Type "echo '   ✅ T-006: Integration tests for full flow      [large]  wave-3'"
Enter
Sleep 1.5s

# --- Scene 5: Diff-Gate review ---
Type "echo ''"
Enter
Type "echo '⏸️  Diff-Gate: Wave 1 ready for human review'"
Enter
Sleep 500ms
Type "echo '   Files: auth/config.py, auth/oauth2_provider.py'"
Enter
Type "echo '   +127 lines  -3 lines  (2 files)'"
Enter
Sleep 500ms
Type "echo ''"
Enter
Type "echo '   [A] Approve   [R] Reject   [S] Select files   [D] Show diff'"
Enter
Sleep 3s
