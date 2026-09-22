"""Batch 2048 benchmark: many games, several modes, one comparison table.

    python benchmark.py --mode random --games 100
    python benchmark.py --mode jev-board --games 100 --headless

The batch itself lives in `runner/benchmark.py`; this file only parses the flags and hands
the parsed namespace to `runner.benchmark.main`.
"""

import argparse
import asyncio
import sys

import labpaths  # noqa: F401

from players import MODES
from runner import benchmark


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", required=True,
                        help="one mode or a comma-separated list of: %s" % ", ".join(MODES))
    parser.add_argument("--games", type=int, default=10, help="games per mode")
    parser.add_argument("--seed", type=int, default=2048,
                        help="base seed; game i of a mode uses seed + i")
    parser.add_argument("--headless", action="store_true",
                        help="hide the browser (headed by default)")
    parser.add_argument("--workers", type=int, default=1, help="concurrent games")
    parser.add_argument("--cdp", default=None,
                        help="attach to a running Chrome, e.g. http://127.0.0.1:9222")
    parser.add_argument("--max-steps", type=int, default=5000, help="moves per game")
    parser.add_argument("--tag", default=None,
                        help="output name (default: <modes>_<games>g_<seed>)")
    parser.add_argument("--timeout", type=float, default=1800.0,
                        help="per-game wall clock seconds before it is cancelled")
    parser.add_argument("--json-out", default=None,
                        help="extra copy of the full summary JSON")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        return asyncio.run(benchmark.main(args))
    except KeyboardInterrupt:
        print("\ninterrupted: partial results were written", flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
