"""Watch jev play 2048. Forever, in a real window, until you stop it.

    python demo.py

No arguments needed. It checks that the 2048 page is being served (starting a static server
itself if it is not), opens a visible Chromium window on the game, opens the live panel in
your own browser, and then plays one game after another with a fresh seed each time. Every
move is printed as it happens, the final board of each game is left on screen for a few
seconds, and the next game starts on its own.

Stop it with Ctrl-C, or just close the game window. Either way the log is closed and the
browser is shut down.

    python demo.py --mode jev-board              # the failure case: one direction, forever
    python demo.py --mode jev-features --speed 1 # one move every 1.2s
    python demo.py --mode jev-state,jev-features # alternate, to see the difference
    python demo.py --mode random                 # no API credentials needed
"""

import argparse
import asyncio
import sys

import labpaths  # noqa: F401

from analysis import metrics
from players import JEV_MODES, MODES
from runner.game_server import ensure_game_server
from runner.interactive import SPEEDS, run_interactive


class Scoreboard:
    """Keeps the running tally while the demo plays, so an interrupt still has the numbers."""

    def __init__(self, keep=200):
        self.keep = keep
        self.outcomes = []
        self.played = 0

    def add(self, outcome, played):
        self.played = played
        self.outcomes.append(outcome)
        if len(self.outcomes) > self.keep:
            self.outcomes.pop(0)
        best = max(self.outcomes, key=lambda item: item.score)
        scored = [item.score for item in self.outcomes]
        reached = sum(1 for item in self.outcomes if item.max_tile >= 256)
        print("    best %d (game %d, %s) · %d played · avg %.0f · 256+ %d/%d"
              % (best.score, best.game_id, best.mode, played,
                 sum(scored) / len(scored), reached, len(self.outcomes)), flush=True)

    def report(self):
        if not self.outcomes:
            print("\nnothing was played.", flush=True)
            return
        print("\n" + "=" * 78)
        print("stopped after %d game%s." % (self.played, "" if self.played == 1 else "s"))
        for mode in dict.fromkeys(item.mode for item in self.outcomes):
            group = [item for item in self.outcomes if item.mode == mode]
            summary = metrics.aggregate(group, mode)
            print("  %-18s games %-3d avg score %-7.0f median %-7.0f best %-6d "
                  "max tile %-5.0f 256+ %4.1f%%"
                  % (mode, summary["games"], summary["average_score"],
                     summary["median_score"], summary["max_score"],
                     summary["average_max_tile"], summary["reached_256_pct"]))
        print("=" * 78, flush=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", default="jev-features",
                        help="one mode, or several comma-separated to alternate per game "
                             "(%s)" % ", ".join(MODES))
    parser.add_argument("--seed", type=int, default=2048, help="first game's seed")
    parser.add_argument("--speed", default="5", choices=sorted(SPEEDS),
                        help="delay between moves: 1x, 5x, 20x or max")
    parser.add_argument("--max-steps", type=int, default=600,
                        help="moves per game; 0 = let every game run to its own end")
    parser.add_argument("--between-games", type=float, default=3.0,
                        help="seconds to leave the finished board on screen")
    parser.add_argument("--shots", dest="shots", action="store_true", default=None,
                        help="mirror the window into the panel even when it is visible "
                             "(capturing a visible window makes it flash)")
    parser.add_argument("--no-shots", dest="shots", action="store_false",
                        help="never screenshot; the panel draws the board from the data")
    parser.add_argument("--shot-interval", type=float, default=0.2,
                        help="seconds between panel screenshots (default: only when headless)")
    parser.add_argument("--dashboard-port", type=int, default=8799)
    parser.add_argument("--no-dashboard", action="store_true", help="skip the live panel")
    parser.add_argument("--no-open", action="store_true",
                        help="do not open the panel in your browser; just print its URL")
    parser.add_argument("--cdp", default=None,
                        help="drive an already-running Chrome, e.g. http://127.0.0.1:9222")
    parser.add_argument("--headless", action="store_true",
                        help="hide the window (the panel still shows a screenshot)")
    parser.add_argument("--log", default=None, help="JSONL path (default logs/demo.jsonl)")
    return parser.parse_args(argv)


def parse_modes(raw):
    modes = [chunk.strip() for chunk in str(raw).split(",") if chunk.strip()]
    unknown = [name for name in modes if name not in MODES]
    if unknown:
        raise SystemExit("unknown mode(s) %s; choose from %s"
                         % (", ".join(unknown), ", ".join(MODES)))
    return tuple(dict.fromkeys(modes))


def main(argv=None):
    args = parse_args(argv)
    modes = parse_modes(args.mode)
    if not args.cdp and any(name in JEV_MODES for name in modes):
        try:
            from jev.client import JevClient

            JevClient()
        except Exception as exc:
            print("cannot start: %s" % exc, file=sys.stderr)
            print("The jev modes need TYPESAFE_API_KEY. Try `python demo.py --mode random`, "
                  "which needs no credentials.", file=sys.stderr)
            return 2

    import os

    log_path = args.log or os.path.join(labpaths.LOGS_DIR, "demo.jsonl")
    board = Scoreboard()
    print("2048 / jev demo — %s. Ctrl-C or close the window to stop."
          % " + ".join(modes), flush=True)
    print("log: %s" % log_path, flush=True)
    try:
        with ensure_game_server():
            asyncio.run(run_interactive(
                modes, seed=args.seed, games=0, max_steps=args.max_steps,
                log_path=log_path, cdp=args.cdp, headless=args.headless, speed=args.speed,
                dashboard=not args.no_dashboard, dashboard_port=args.dashboard_port,
                open_dashboard=not args.no_open, on_outcome=board.add,
                between_games=args.between_games, shots=args.shots,
                shot_interval=args.shot_interval or 10_000))
    except KeyboardInterrupt:
        pass
    board.report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
