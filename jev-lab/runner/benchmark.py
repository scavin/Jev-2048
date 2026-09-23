"""Batch benchmark: many games, several modes, one comparison table.

    python benchmark.py --mode random,greedy,heuristic --games 100 --headless
    python benchmark.py --mode jev-board --games 100 --workers 4

Every game is independent — its own seeded navigation and its own freshly built player —
so a game's numbers are a function of its seed alone and never of `--workers`. Games of one
mode run `--workers` at a time over a pool of browser sessions, one session per worker; a
game that raises, or that overruns `--timeout`, is recorded as a failed row instead of
ending the batch. `KeyboardInterrupt` still closes every session and writes what finished.

Artifacts, all named after `--tag`:

* `logs/<tag>.jsonl`            one line per executed move, all modes in one file
* `results/<tag>_games.csv`     one row per game, `metrics.GAME_FIELDS`
* `results/<tag>_summary.json`  the whole run, per-mode summaries under `modes`
* `results/<tag>_summary.csv`   one row per mode, `metrics.summary_fields()`

`--cdp` drives one already-running tab, so it runs with a single worker and says so. The
JSONL is truncated once at the start of a run, so a tag always names exactly one run.
"""

import asyncio
import os
import time
from dataclasses import dataclass

import labpaths  # noqa: F401

from analysis import metrics
from game.adapter import GameAdapter
from players import LAYA_MODES, MODES, build
from runner.browser import BrowserSession
from runner.game_loop import GameOutcome, LogWriter, gather_limited, play_one

REACHED = (256, 512, 1024, 2048, 4096)
FAILED_ENDINGS = ("aborted", "timeout")


def parse_modes(raw):
    """`--mode` as a validated, de-duplicated list, in the order the user wrote it."""
    modes = []
    for chunk in str(raw).split(","):
        mode = chunk.strip()
        if not mode:
            continue
        if mode not in MODES:
            raise SystemExit("unknown mode %r; choose from %s" % (mode, ", ".join(MODES)))
        if mode not in modes:
            modes.append(mode)
    if not modes:
        raise SystemExit("--mode needs at least one of %s" % ", ".join(MODES))
    return modes


def default_tag(modes, games, seed):
    return "%s_%dg_%d" % ("+".join(modes), games, seed)


def failed_outcome(mode, game_id, seed, ended, reason, stats=None):
    """A row for a game that never produced one, so the report can still count it.

    `stats` carries whatever the game had already done when it was cut short, so a
    cancelled game is reported for the moves it actually made instead of as a zero.
    """
    stats = dict(stats or {})
    return GameOutcome(
        game_id=game_id, seed=seed, mode=mode,
        score=stats.get("score", 0), steps=stats.get("steps", 0),
        max_tile=stats.get("max_tile", 0),
        reached={str(tile): stats.get("max_tile", 0) >= tile for tile in REACHED},
        ended=ended, abort_reason=reason,
        tag_counts=stats.get("tag_counts", {}), invalid_moves=stats.get("invalid_moves", 0),
        latencies=stats.get("latencies", []), wall_ms=stats.get("wall_ms", []),
        jev_calls=stats.get("jev_calls", 0), jev_rejections=stats.get("jev_rejections", 0),
        tokens_in=stats.get("tokens_in", 0), tokens_out=stats.get("tokens_out", 0),
        kept_playing=stats.get("kept_playing", False))


@dataclass
class _Job:
    """One game's assignment: which mode, which game of that mode, and the budget."""

    mode: str
    game_id: int
    seed: int
    count: int
    max_steps: int
    timeout: float


async def _run_game(pool, writer, finished, job):
    """Play one game on a borrowed adapter. Never raises for a game-level failure."""
    adapter = await pool.get()
    started = time.perf_counter()
    stats = {}
    try:
        try:
            outcome = await asyncio.wait_for(
                play_one(adapter, build(job.mode, seed=job.seed), job.mode, job.game_id,
                         job.seed, max_steps=job.max_steps, log=writer, stats=stats),
                job.timeout)
        except asyncio.TimeoutError:
            outcome = failed_outcome(job.mode, job.game_id, job.seed, "timeout",
                                     "wall clock over %.1fs" % job.timeout, stats)
        except Exception as exc:
            outcome = failed_outcome(job.mode, job.game_id, job.seed, "aborted",
                                     "%s: %s" % (type(exc).__name__, exc), stats)
    finally:
        pool.put_nowait(adapter)
    finished.append(outcome)
    print("%-12s game %d/%d  score %-6d steps %-5d max_tile %-5d %-9s %.1fs"
          % (job.mode, job.game_id + 1, job.count, outcome.score, outcome.steps,
             outcome.max_tile, outcome.ended, time.perf_counter() - started), flush=True)
    return outcome


async def _start_sessions(count, headless, cdp):
    sessions = []
    try:
        for _ in range(count):
            session = BrowserSession(headless=headless, cdp=cdp)
            await session.start()
            sessions.append(session)
    except BaseException:
        await _close_sessions(sessions)
        raise
    return sessions


async def _close_sessions(sessions):
    for session in sessions:
        try:
            await session.close()
        except Exception as exc:  # a stuck browser must not hide the results
            print("  (session close failed: %s)" % exc, flush=True)


def write_report(args, modes, tag, workers, cdp, finished, paths, started):
    """Aggregate whatever finished and write all four artifacts."""
    outcomes = sorted(finished, key=lambda outcome: (modes.index(outcome.mode),
                                                     outcome.game_id))
    summaries = []
    for mode in modes:
        group = [outcome for outcome in outcomes if outcome.mode == mode]
        if group:
            summaries.append(metrics.aggregate(group, mode))
    # `metrics.aggregate` emits `loop_rate` itself.
    failures = [outcome for outcome in outcomes if outcome.ended in FAILED_ENDINGS]
    payload = {
        "tag": tag,
        "seed": args.seed,
        "games": args.games,
        "max_steps": args.max_steps,
        "timeout": args.timeout,
        "headless": args.headless,
        "workers": workers,
        "workers_requested": args.workers,
        "cdp": cdp,
        "modes": {summary["mode"]: summary for summary in summaries},
        "summaries": summaries,
        "failed": len(failures),
        "failures": [{"mode": outcome.mode, "game_id": outcome.game_id,
                      "seed": outcome.seed, "ended": outcome.ended,
                      "error": outcome.abort_reason} for outcome in failures],
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    metrics.write_csv(paths["games_csv"], [metrics.game_row(o) for o in outcomes],
                      metrics.GAME_FIELDS)
    metrics.write_csv(paths["summary_csv"], summaries, metrics.summary_fields())
    metrics.write_json(paths["summary_json"], payload)
    if paths.get("json_out"):
        metrics.write_json(paths["json_out"], payload)
    return payload


def print_report(payload, paths):
    summaries = payload["summaries"]
    print()
    print(metrics.comparison_table(summaries))
    calls = sum(summary["jev_calls"] for summary in summaries)
    if calls:
        print("\njev calls: %d (rejections %d, tokens in %d / out %d)"
              % (calls, sum(s["jev_rejections"] for s in summaries),
                 sum(s["tokens_in"] for s in summaries),
                 sum(s["tokens_out"] for s in summaries)))
    if payload["failed"]:
        print("\nfailed games: %d" % payload["failed"])
        for failure in payload["failures"]:
            print("  %s game %d seed %d -> %s: %s"
                  % (failure["mode"], failure["game_id"], failure["seed"],
                     failure["ended"], failure["error"]))
    print("\nwrote:")
    for label in ("log", "games_csv", "summary_json", "summary_csv", "json_out"):
        if paths.get(label):
            print("  %-13s %s" % (label, paths[label]))
    print("  %-13s %.1fs" % ("elapsed", payload["elapsed_s"]))


async def main(args=None):
    """Run the batch described by `args` (the CLI namespace from `benchmark.py`)."""
    if args is None:
        import benchmark as cli  # the project-root entry point owns the flags

        args = cli.parse_args()

    modes = parse_modes(args.mode)
    tag = args.tag or default_tag(modes, args.games, args.seed)
    workers = max(1, args.workers)
    cdp = args.cdp
    if cdp and workers > 1:
        print("--cdp drives one attached tab: workers %d -> 1" % workers, flush=True)
        workers = 1
    if any(name in LAYA_MODES for name in modes) and workers > 1:
        # One local checkpoint on one GPU. Concurrent games would only queue on the model
        # anyway, and the client serializes them regardless.
        print("laya drives one local model: workers %d -> 1" % workers, flush=True)
        workers = 1

    paths = {
        "log": os.path.join(labpaths.LOGS_DIR, "%s.jsonl" % tag),
        "games_csv": os.path.join(labpaths.RESULTS_DIR, "%s_games.csv" % tag),
        "summary_json": os.path.join(labpaths.RESULTS_DIR, "%s_summary.json" % tag),
        "summary_csv": os.path.join(labpaths.RESULTS_DIR, "%s_summary.csv" % tag),
    }
    if args.json_out:
        paths["json_out"] = args.json_out

    print("tag=%s modes=%s games=%d seed=%d max_steps=%d timeout=%.0fs headless=%s "
          "workers=%d cdp=%s"
          % (tag, "+".join(modes), args.games, args.seed, args.max_steps, args.timeout,
             args.headless, workers, cdp or "off"), flush=True)
    open(paths["log"], "w").close()  # a tag names one run

    finished = []
    sessions = []
    started = time.perf_counter()
    try:
        try:
            sessions = await _start_sessions(workers, args.headless, cdp)
            print("browser=%s x%d" % (sessions[0].mode, len(sessions)), flush=True)
            adapters = [GameAdapter(session.tab) for session in sessions]
            pool = asyncio.Queue()
            for adapter in adapters:
                pool.put_nowait(adapter)
            for mode in modes:
                print("\n--- %s: %d game%s on %s ---"
                      % (mode, args.games, "" if args.games == 1 else "s", paths["log"]),
                      flush=True)
                writer = LogWriter(paths["log"])
                try:
                    jobs = [_Job(mode, index, args.seed + index, args.games,
                                 args.max_steps, args.timeout)
                            for index in range(args.games)]
                    # A generator, not a list: on an interrupt the games that never started
                    # are then never built, so no coroutine is left un-awaited.
                    await gather_limited(
                        (_run_game(pool, writer, finished, job) for job in jobs), workers)
                finally:
                    writer.close()
        finally:
            await _close_sessions(sessions)
    finally:
        payload = write_report(args, modes, tag, workers, cdp, finished, paths, started)
        print_report(payload, paths)

    return 0 if finished else 1
