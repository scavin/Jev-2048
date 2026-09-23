"""Run 2048 with a model in a visible browser, one move at a time.

    python run.py --mode laya-board
    python run.py --mode jev-features --speed 1
    python run.py --mode jev-history --cdp http://127.0.0.1:9222

The browser is headed by default: the point of this entry point is to watch the decisions
happen. `--headless` exists for unattended runs; `benchmark.py` is the batch path.
"""

import argparse
import asyncio
import os
import sys

import labpaths  # noqa: F401

from analysis import metrics
from players import MODES
from runner.interactive import SPEEDS, run_interactive


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", default="laya-board",
                        help="one of %s (comma-separated allowed)" % ", ".join(MODES))
    parser.add_argument("--seed", type=int, default=2048, help="spawn stream seed")
    parser.add_argument("--games", type=int, default=1,
                        help="games to play in a row; 0 = play until stopped")
    parser.add_argument("--max-steps", type=int, default=5000, help="moves per game")
    parser.add_argument("--speed", default="5", choices=sorted(SPEEDS),
                        help="delay between moves: 1x, 5x, 20x or max")
    parser.add_argument("--cdp", default=None,
                        help="attach to a running Chrome, e.g. http://127.0.0.1:9222")
    parser.add_argument("--headless", action="store_true",
                        help="hide the browser (the dashboard still shows a screenshot)")
    parser.add_argument("--no-dashboard", action="store_true", help="skip the live panel")
    parser.add_argument("--dashboard-port", type=int, default=8799)
    parser.add_argument("--no-open", action="store_true",
                        help="do not open the dashboard in your browser; just print its URL")
    parser.add_argument("--log", default=None, help="JSONL path (default logs/<mode>.jsonl)")
    return parser.parse_args(argv)


async def run(args):
    outcomes = []
    for mode in args.mode.split(","):
        mode = mode.strip()
        if mode not in MODES:
            raise SystemExit("unknown mode %r; choose from %s" % (mode, ", ".join(MODES)))
        log_path = args.log or os.path.join(labpaths.LOGS_DIR, "%s.jsonl" % mode)
        print("=" * 78)
        print("mode %s   log %s" % (mode, log_path))
        print("=" * 78)
        outcomes.extend(await run_interactive(
            mode, seed=args.seed, games=args.games, max_steps=args.max_steps,
            log_path=log_path, cdp=args.cdp, headless=args.headless, speed=args.speed,
            dashboard=not args.no_dashboard, dashboard_port=args.dashboard_port,
            open_dashboard=not args.no_open))
    return outcomes


def main(argv=None):
    args = parse_args(argv)
    outcomes = []
    try:
        outcomes = asyncio.run(run(args))
    except KeyboardInterrupt:
        # `--games 0` runs until stopped, so this is a normal way to end a session.
        print("\nstopped.", flush=True)
        return 0
    if not outcomes:
        return 1
    print()
    for mode in dict.fromkeys(outcome.mode for outcome in outcomes):
        group = [outcome for outcome in outcomes if outcome.mode == mode]
        summary = metrics.aggregate(group, mode)
        print("%-13s games=%d  avg score=%.0f  median=%.0f  max=%d  avg steps=%.0f  "
              "max tile=%.0f  avg latency=%.0f ms"
              % (mode, summary["games"], summary["average_score"],
                 summary["median_score"], summary["max_score"], summary["average_steps"],
                 summary["average_max_tile"], summary["average_latency_ms"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
