import argparse
import asyncio
import sys
from yani_engine.core.orchestrator import LLMOrchestrator
from yani_engine.core.config import config

async def main_async():
    parser = argparse.ArgumentParser(description="yani-engine CLI")
    parser.add_argument("command", choices=["start", "execute", "resume", "report", "rollback", "update-docs", "audit", "iterate", "status"])
    parser.add_argument("--model", help="Model override")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose mode")
    parser.add_argument("--budget-limit", type=int)
    parser.add_argument("--budget-threshold", type=int)
    parser.add_argument("--start-at", type=int)
    
    args, unknown = parser.parse_known_args()

    # Hydrate the global config singleton with CLI overrides
    if args.model: config.model = args.model
    if args.verbose: config.verbose = args.verbose
    if args.budget_limit: config.budget_limit = args.budget_limit
    if args.budget_threshold: config.budget_threshold_pct = args.budget_threshold
    if args.start_at: config.start_at_index = args.start_at

    # Orchestrator no longer needs initialization parameters!
    cli = LLMOrchestrator()
    await cli.run(args.command, unknown)

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
