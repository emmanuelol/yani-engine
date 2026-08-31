# yani-engine-demo.tape — Full Harness Demo: Blast Radius → Fail-Close → Atomic Waves → Diff-Gate
# Showcases the complete safety-first execution pipeline of yani-engine.
#
# Usage: vhs yani-engine-demo.tape
# Output: yani-engine-demo.gif

Output yani-engine-demo.gif
Set FontSize 22
Set Width 1200
Set Height 800
Set Theme "Dracula"
Set TypingSpeed 80ms

# --- Scene 1: User kicks off a dangerous refactor ---
Sleep 500ms
Type "/yani-engine start 'Refactor all instances of the v1 Auth API to use the new v2 JWT endpoints'"
Enter
Sleep 2s

# --- Scene 2: CodeGraph blast radius analysis ---
Type "echo ''"
Enter
Type "echo '── yani-engine ── Blast Radius Analysis ─────────────'"
Enter
Sleep 500ms
Type "echo '🔍 Querying CodeGraph for blast radius...'"
Enter
Sleep 2s

Type "echo '   Scanning symbol graph: auth_v1.py → session.py → middleware.py'"
Enter
Sleep 300ms
Type "echo '   Tracing callers:       api/v1/login.py, api/v1/register.py, api/v1/refresh.py'"
Enter
Sleep 300ms
Type "echo '   Mapping test surface:  tests/test_auth.py, tests/test_session.py'"
Enter
Sleep 1s

# --- Scene 3: Blast radius EXCEEDED — danger detected ---
Type "echo ''"
Enter
Type "echo '❌ ERROR: Blast radius exceeded (42 symbols > 20).'"
Enter
Sleep 500ms
Type "echo '   Affected: 42 functions across 7 modules'"
Enter
Sleep 300ms
Type "echo '   Threshold: 20 symbols (configurable in .yani/config.yml)'"
Enter
Sleep 1.5s

# --- Scene 4: Fail-Closed guardrail enforced ---
Type "echo ''"
Enter
Type "echo '🛡️  Fail-Closed: Dangerous mutation blocked.'"
Enter
Sleep 300ms
Type "echo '   Reason: Single-wave refactor risks cascading regressions'"
Enter
Sleep 300ms
Type "echo '   Action: Automatic decomposition into safe atomic waves'"
Enter
Sleep 2s

# --- Scene 5: Auto-decomposition into atomic waves ---
Type "echo ''"
Enter
Type "echo '🔄 Decomposing into safer, atomic waves...'"
Enter
Sleep 1.5s

Type "echo '   ✅ Task T-001 registered: Update auth schema               [small effort]  wave-1'"
Enter
Sleep 300ms
Type "echo '   ✅ Task T-002 registered: Update API endpoint               [small effort]  wave-1'"
Enter
Sleep 300ms
Type "echo '   ✅ Task T-003 registered: Migrate session token provider    [medium effort] wave-2'"
Enter
Sleep 300ms
Type "echo '   ✅ Task T-004 registered: Update middleware JWT validation  [medium effort] wave-2'"
Enter
Sleep 300ms
Type "echo '   ✅ Task T-005 registered: Integration test suite for v2     [large effort]  wave-3'"
Enter
Sleep 1.5s

# --- Scene 6: Diff-Gate approval prompt ---
Type "echo ''"
Enter
Type "echo '── yani-engine ── Diff-Gate ──────────────────────────'"
Enter
Sleep 500ms
Type "echo '⏸️  Wave 1 ready for human review.'"
Enter
Sleep 300ms
Type "echo ''"
Enter
Type "echo '   Tasks in this wave:'"
Enter
Type "echo '     T-001: Update auth schema'"
Enter
Type "echo '     T-002: Update API endpoint'"
Enter
Sleep 300ms
Type "echo ''"
Enter
Type "echo '   Estimated impact: +89 lines, -12 lines (3 files)'"
Enter
Sleep 500ms
Type "echo ''"
Enter
Type "echo '   [A] Approve wave   [R] Reject   [S] Select tasks   [D] Show diff'"
Enter
Sleep 3s
