"""Play 2048 with jev, or with a baseline, and report measurable performance.

Every policy drives the same black-box client (`game-test/game_client.py`) against the real
page, so the score is the page's own score, not a simulator's.

Usage:
  /tmp/pwenv/bin/python jev-test/play.py --policies random,greedy,jev \
      --games 3 --max-moves 150 --prompt neutral --json-out /tmp/jev2048/jev_neutral.json
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "game-test"))

import game_client  # noqa: E402
import reference2048 as ref  # noqa: E402
from run_tests import PlaywrightTab  # noqa: E402  (the suite's own tab adapter)

from jev_client import JevClient  # noqa: E402

NAMES = ("up", "right", "down", "left")  # index == reference2048 direction constant

# A fixed opening board, so every policy starts from the same position. Spawns after that
# still come from the page's own RNG and cannot be controlled.
FIXED_START = [[0, 0, 0, 0], [0, 2, 0, 0], [0, 0, 0, 0], [2, 0, 0, 0]]


def legal_moves(board):
    return [name for index, name in enumerate(NAMES) if ref.move(board, index)[2]]


def greedy_move(board, legal):
    """One-ply baseline: keep the board open, then take the merge."""
    best, best_key = None, None
    for name in legal:
        after, gained, _ = ref.move(board, NAMES.index(name))
        key = (len(ref.empty_cells(after)), gained)
        if best_key is None or key > best_key:
            best_key, best = key, name
    return best


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


async def start_position(client, fixed_start):
    if fixed_start:
        state = game_client.GameClient.state_from_board(FIXED_START, score=0)
        await client.seed(state, best_score=0, clear=True)
    else:
        await client.restart()


async def play_game(client, policy, max_moves, rng, jev, fixed_start):
    await start_position(client, fixed_start)
    history = []
    api_ms = []
    moves = decisions = forced = 0
    tokens_in = tokens_out = 0
    latencies = []
    started = time.perf_counter()

    while moves < max_moves:
        snap = await client.read()
        board = snap["board"]

        if snap["messageVisible"] and "game-won" in snap["messageClass"]:
            await client.click(".keep-playing-button")
            snap = await client.read()
            board = snap["board"]

        if not ref.moves_available(board):
            break

        legal = legal_moves(board)
        if not legal:
            break

        if len(legal) == 1:
            name = legal[0]
            forced += 1
        elif policy == "jev":
            decision = jev.choose(board, snap["score"], ref.winning_tile(board), legal, history)
            name = decision["name"]
            decisions += 1
            api_ms.append(decision["latency_ms"])
            tokens_in += decision["usage"].get("input_tokens", 0) or 0
            tokens_out += decision["usage"].get("output_tokens", 0) or 0
            latencies.append(decision["latency_ms"])
        elif policy == "random":
            name = rng.choice(legal)
        elif policy == "greedy":
            name = greedy_move(board, legal)
        else:
            raise ValueError("unknown policy %r" % policy)

        before = board
        await client.press(NAMES.index(name))
        history.append(name)
        moves += 1
        after = (await client.read())["board"]
        if after == before:
            raise RuntimeError("policy %s produced a no-op on move %d" % (policy, moves))

    final = await client.read()
    return {
        "policy": policy,
        "moves": moves,
        "score": final["score"],
        "max_tile": ref.winning_tile(final["board"]),
        "board": final["board"],
        "decisions": decisions,
        "forced": forced,
        "wall_ms": round((time.perf_counter() - started) * 1000),
        "api_ms_mean": round(statistics.mean(api_ms)) if api_ms else None,
        "api_ms_median": round(statistics.median(api_ms)) if api_ms else None,
        "api_ms_p95": percentile(api_ms, 0.95),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "reached_2048": ref.winning_tile(final["board"]) >= 2048,
    }


def summarise(games):
    if not games:
        return {"games": 0, "error": "no completed games"}
    scores = [g["score"] for g in games]
    return {
        "games": len(games),
        "score_mean": round(statistics.mean(scores), 1),
        "score_median": statistics.median(scores),
        "score_min": min(scores),
        "score_max": max(scores),
        "max_tile_best": max(g["max_tile"] for g in games),
        "moves_mean": round(statistics.mean([g["moves"] for g in games]), 1),
        "decisions_total": sum(g["decisions"] for g in games),
        "wall_s_total": round(sum(g["wall_ms"] for g in games) / 1000, 1),
        "api_ms_median": statistics.median([g["api_ms_median"] for g in games if g["api_ms_median"]] or [0]) or None,
        "win_rate": round(sum(1 for g in games if g["reached_2048"]) / len(games), 2),
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8792/index.html")
    parser.add_argument("--policies", default="jev")
    parser.add_argument("--games", default="1",
                        help="games per policy: one number, or a comma list matching --policies")
    parser.add_argument("--max-moves", type=int, default=150)
    parser.add_argument("--random-start", action="store_true",
                        help="use the page's own random opening instead of the shared fixed board")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--prompt", default="neutral", choices=["neutral", "hinted"])
    parser.add_argument("--json-out")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--settle", type=float, default=0.08,
                        help="seconds to let input reach the page before the first read")
    parser.add_argument("--poll", type=float, default=0.03,
                        help="stability-poll interval")
    parser.add_argument("--game-timeout", type=int, default=900,
                        help="abort a single game after this many seconds")
    args = parser.parse_args()

    from playwright.async_api import async_playwright

    policies = [p.strip() for p in args.policies.split(",") if p.strip()]
    counts = [int(value) for value in str(args.games).split(",")]
    if len(counts) == 1:
        counts = counts * len(policies)
    if len(counts) != len(policies):
        raise SystemExit("--games must be one number or one per policy")
    rng = random.Random(args.seed)
    report = {"prompt": args.prompt, "max_moves": args.max_moves, "games": {}, "runs": []}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.headed)
        page = await browser.new_page(viewport={"width": 520, "height": 700})
        # A browser that dies mid-run must surface as an error, not as an endless wait.
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(30000)
        await page.goto(args.url, wait_until="load")
        client = game_client.GameClient(
            PlaywrightTab(page), url=args.url,
            settle_seconds=args.settle, poll_interval=args.poll,
        )

        jev = None
        if "jev" in policies:
            jev = JevClient(prompt=args.prompt)

        for policy, count in zip(policies, counts):
            games = []
            for index in range(count):
                try:
                    result = await asyncio.wait_for(
                        play_game(client, policy, args.max_moves, rng, jev, not args.random_start),
                        timeout=args.game_timeout,
                    )
                except asyncio.TimeoutError:
                    result = {"policy": policy, "error": "game timeout after %ds" % args.game_timeout,
                              "moves": None, "score": None, "max_tile": None, "decisions": 0,
                              "forced": 0, "wall_ms": args.game_timeout * 1000, "api_ms_median": None,
                              "reached_2048": False}
                result["game"] = index + 1
                games.append(result)
                report["runs"].append(result)
                report["games"][policy] = summarise([g for g in games if g.get("score") is not None])
                print(json.dumps(result), flush=True)
                # Rewrite after every game so progress is observable while the run is live.
                if args.json_out:
                    with open(args.json_out, "w") as handle:
                        json.dump(report, handle, indent=2)

        await browser.close()

    print(json.dumps({"summary": report["games"]}, indent=2))
    if args.json_out:
        with open(args.json_out, "w") as handle:
            json.dump(report, handle, indent=2)
        print("wrote", args.json_out)


if __name__ == "__main__":
    asyncio.run(main())
