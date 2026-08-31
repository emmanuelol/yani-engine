# yani-skill-demo.tape — yani-skill Lite Mode: Convention-aware execution
# Demonstrates: co-change detection, convention guards, plan adjustment, Diff-Gate
#
# Usage: vhs yani-skill-demo.tape
# Output: yani-skill-demo.gif

Output yani-skill-demo.gif
Set FontSize 22
Set Width 1200
Set Height 800
Set Theme "Dracula"
Set TypingSpeed 80ms

# --- Scene 1: User invokes yani-skill ---
Sleep 500ms
Type "/yani-skill implement 'Add rate limiting to the login route'"
Enter
Sleep 2s

# --- Scene 2: Reconnaissance phase ---
Type "echo ''"
Enter
Type "echo '── yani-skill ── Phase 1: Recon ──────────────────────'"
Enter
Sleep 500ms
Type "echo '🔍 Analyzing Git co-change history for hidden conventions...'"
Enter
Sleep 2s

Type "echo '   Target: auth/routes.py'"
Enter
Sleep 300ms
Type "echo '   Scanning 847 commits for co-change patterns...'"
Enter
Sleep 1.5s

# --- Scene 3: Convention guard triggered ---
Type "echo ''"
Enter
Type "echo '🛡️  Convention Guard Detected'"
Enter
Sleep 500ms
Type "echo '   File pair:  auth/routes.py ↔ docs/api_limits.md'"
Enter
Sleep 300ms
Type "echo '   Co-change correlation: 88% (22/25 commits)'"
Enter
Sleep 300ms
Type "echo '   Verdict: HARD COUPLING — docs/api_limits.md MUST be updated'"
Enter
Sleep 2s

# --- Scene 4: Plan adjustment ---
Type "echo ''"
Enter
Type "echo '── yani-skill ── Phase 2: Plan ───────────────────────'"
Enter
Sleep 500ms
Type "echo '✅ Adjusting execution plan to include documentation update.'"
Enter
Sleep 1s

Type "echo ''"
Enter
Type "echo '   Task T-01: Add rate limiter middleware       [auth/routes.py]'"
Enter
Sleep 300ms
Type "echo '     └─ convention_guard: Update docs/api_limits.md'"
Enter
Sleep 300ms
Type "echo '   Task T-02: Update API rate limit docs        [docs/api_limits.md]'"
Enter
Sleep 300ms
Type "echo '     └─ verification: pytest tests/test_routes.py -q'"
Enter
Sleep 1.5s

# --- Scene 5: Diff-Gate approval prompt ---
Type "echo ''"
Enter
Type "echo '── yani-skill ── Diff-Gate ───────────────────────────'"
Enter
Sleep 500ms
Type "echo '⏸️  Human review required before execution.'"
Enter
Sleep 300ms
Type "echo ''"
Enter
Type "echo '   Files to modify:'"
Enter
Type "echo '     • auth/routes.py          (+34 lines)'"
Enter
Type "echo '     • docs/api_limits.md      (+12 lines)'"
Enter
Type "echo '     • tests/test_routes.py    (+28 lines)'"
Enter
Sleep 500ms
Type "echo ''"
Enter
Type "echo '   [A] Approve plan   [R] Reject   [E] Edit tasks'"
Enter
Sleep 3s
