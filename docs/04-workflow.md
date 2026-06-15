# Session Workflow

## 1. Initialization
You navigate to the project you wish to improve and run `dumbledoer start`. DumbleDoer maps its CodeGraph context and `memory.md` tracking directly to this active directory.

## 2. Planning
The agent creates a `memory.md` file in the current working directory, registering the atomic task plan without dragging in DumbleDoer's own orchestrator scripts.

## 3. Execution
When running `dumbledoer execute`, the central DumbleDoer logic executes tasks using its isolated `.venv`. It performs localized semantic audits and applies changes directly to your current project.

## 4. Completion
DumbleDoer generates the `/report` locally and synchronizes `memory.md`. Your project is updated, while DumbleDoer safely returns to idle in its centralized location.
