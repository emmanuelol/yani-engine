import sys
import os
import asyncio
import argparse
from dumbledoer.core.orchestrator import LLMOrchestrator
from dumbledoer.core.state import ASTMemoryMapper

GUI_DIFF_ENABLED = False

async def main_async():
    parser = argparse.ArgumentParser(description="DumbleDoer CLI")
    parser.add_argument(
        "command",
        choices=["start", "execute", "resume", "report", "rollback", "update-docs", "audit", "iterate", "status"],
        help="The dumbledoer command to run"
    )
    parser.add_argument("--model", default=os.getenv("AGY_MODEL", "gemini-3.6-flash"), help="Model override")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose mode (e.g. GUI diff-gate in VS Code)")
    parser.add_argument("--budget-limit", type=int, help="Override budget_limit for token tracking")
    parser.add_argument("--budget-threshold", type=int, help="Override budget_threshold_pct (e.g. 80)")
    
    import shlex
    flat_args = []
    for arg in sys.argv[1:]:
        if " " in arg and (arg.startswith("-") or "--" in arg):
            flat_args.extend(shlex.split(arg))
        else:
            flat_args.append(arg)
    args, unknown = parser.parse_known_args(flat_args)

    global GUI_DIFF_ENABLED
    GUI_DIFF_ENABLED = args.verbose

    if GUI_DIFF_ENABLED:
        try:
            with open("memory.md", "r", encoding="utf-8") as f:
                content = f.read()
            start, end = ASTMemoryMapper.locate_heading_block(content, "##", "Config")
            if start != -1:
                config_lines = content.splitlines()[start:end]
                if any("gui_diff_enabled: false" in line.lower() for line in config_lines):
                    GUI_DIFF_ENABLED = False
        except FileNotFoundError:
            pass

    cli = LLMOrchestrator(budget_limit=args.budget_limit, budget_threshold=args.budget_threshold)
    await cli.run(args.command, unknown, model=args.model)

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
