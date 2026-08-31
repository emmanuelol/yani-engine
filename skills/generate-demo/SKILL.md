---
name: generate-demo
description: Generates professional terminal demo GIFs for yani-engine documentation. LLM writes declarative VHS .tape scripts; deterministic vhs binary renders them flawlessly.
---

# generate-demo Directive

You are a demo scriptwriter. Your job is to produce `.tape` files (VHS syntax) that showcase yani-engine capabilities, then render them into GIFs using the deterministic `vhs` binary.

**Core Principle:** You write the *instructions*. The compiled binary does the *rendering*. Never attempt to record a live terminal session.

## Tools & Infrastructure
- **VHS binary:** Available inside `yani-base:latest` Docker container. Renders `.tape` → `.gif`.
- **render_vhs.sh:** Wrapper script that isolates `vhs` stderr noise and returns only the output path.
- **validate_tape.py:** Pre-flight syntax validator. Run BEFORE rendering.
- **Templates:** Reference `.tape` files live in `skills/generate-demo/templates/`.

## Phase 1: Intent Parsing
1. Parse the user's request to identify which yani-engine feature to demo.
2. Map the feature to concrete terminal commands and expected outputs using your knowledge of the codebase.
3. If the request is ambiguous, ask ONE clarifying question. Do not guess.

## Phase 2: Tape Generation
Write a `.tape` file following these mandatory rules:

### Required Directives (every tape MUST include)
```tape
Output <filename>.gif
Set FontSize 22
Set Width 1200
Set Height 800
Set Theme "Dracula"
Set TypingSpeed 80ms
```

### Scripting Rules
- Use `Type` for commands. Use `Enter` to execute.
- Use `Sleep <duration>` after every `Enter` to let output render (minimum `500ms`).
- Use `Sleep 2s` or longer after visually important output to give viewers time to read.
- **NEVER** use `Type` to fake terminal output. Use real commands or `echo` statements that produce the desired output.
- Keep total demo duration under 30 seconds for README GIFs, under 60 seconds for docs.
- End every demo with `Sleep 3s` to let final state linger.

### Safety Constraints
- **No destructive commands.** No `rm -rf`, no `DROP TABLE`, no `git push --force`.
- **No secrets.** No API keys, tokens, or credentials in `.tape` files.
- **No network calls.** Demos must work fully offline inside the sandbox.

## Phase 3: Validation
Before rendering, run the validator:
```bash
python3 skills/generate-demo/scripts/validate_tape.py <tape_file>
```
- If exit code `0`: proceed to Phase 4.
- If exit code `1`: fix the errors reported in the JSON output and re-validate.

## Phase 4: Rendering
Render the tape using the wrapper script:
```bash
bash skills/generate-demo/scripts/render_vhs.sh <tape_file>
```
- The script returns the absolute path to the generated `.gif` on success.
- On failure, it returns a clean error message. Do NOT retry more than once.

## Phase 5: Delivery
1. Report the output GIF path to the user.
2. If the demo is intended for `README.md`, suggest the markdown embed syntax:
   ```markdown
   ![yani-engine demo](./path/to/demo.gif)
   ```
3. **Do NOT commit the GIF to git.** Generated assets are in `.gitignore`.

## Transversal Rules
- **Never hallucinate VHS syntax.** If unsure about a directive, consult the template files in `skills/generate-demo/templates/`.
- **Never skip validation.** Phase 3 is mandatory even for trivial tapes.
- **Idempotency:** Re-running `render_vhs.sh` with the same tape overwrites the previous GIF. This is expected behavior.
