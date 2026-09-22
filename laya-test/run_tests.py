"""Differential test suite for the 2048 game, with Laya as an advisory judge.

The suite drives the real page through real keyboard input and compares every observed
board against reference2048.py, an independent implementation of the rules. Randomness is
never controlled: a move is asserted to produce the reference slide plus exactly one new
tile of value 2 or 4, which is a stronger check than pinning a seeded RNG.

Laya's role is deliberately narrow — triaging failures and cross-checking user-facing
messages — because measurement (CALIBRATION.md) shows it cannot read a board.

Standalone use:

    pip install playwright && playwright install chromium
    python laya-test/run_tests.py --url http://127.0.0.1:8792/index.html

"""

import argparse
import asyncio
import json
import pathlib
import random
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import laya_judge  # noqa: E402
import reference2048 as ref  # noqa: E402
from game_client import DIRECTION_NAMES, GameClient  # noqa: E402

# Full board with exactly one merge available. Merging the two 2s frees (0,3), whose
# neighbours are 16 and 64, so the tile spawned there can never create a new merge:
# the game over verdict after this move is deterministic rather than lucky.
DEAD_NEXT_MOVE = [
    [2, 2, 8, 16],
    [8, 16, 32, 64],
    [16, 32, 64, 128],
    [32, 64, 128, 256],
]

WIN_NEXT_MOVE = [
    [1024, 1024, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]


def tile_count(board):
    return sum(1 for row in board for v in row if v)


def diff_cells(expected, actual):
    return [(r, c, expected[r][c], actual[r][c])
            for r in range(4) for c in range(4) if expected[r][c] != actual[r][c]]


def fmt_board(board):
    return " | ".join(" ".join(str(v or ".") for v in row) for row in board)


class Suite:
    def __init__(self, game, laya=None, trace=False):
        self.game = game
        self.laya = laya
        self.trace = trace
        self.checks = 0
        self.failures = []
        self.message_checks = []

    def say(self, line):
        if self.trace:
            print(line, flush=True)

    def check(self, condition, test, kind, **fields):
        self.checks += 1
        ok = bool(condition)
        if self.trace:
            print("    %-4s %-24s %s" % ("ok" if ok else "FAIL", test, kind), flush=True)
        if not ok:
            evidence = laya_judge.triage_evidence(kind, **fields)
            self.failures.append({
                "test": test,
                "kind": kind,
                "evidence": evidence,
                "detail": {k: v for k, v in fields.items()},
            })
        return ok

    # ------------------------------------------------------------------ invariants

    def invariants(self, snap, test):
        illegal = [v for row in snap["board"] for v in row
                   if v and not (v >= 2 and (v & (v - 1)) == 0)]
        self.check(not illegal, test, "illegal_tile", value=illegal[0] if illegal else 0)
        if snap["modelBoard"] is not None:
            self.check(snap["board"] == snap["modelBoard"], test, "dom_model_mismatch",
                       model=snap["modelBoard"], dom=snap["board"])
        self.check(snap["best"] >= snap["score"], test, "best_below_score",
                   best=snap["best"], score=snap["score"])

    # ------------------------------------------------------------------ move engine

    async def check_move(self, direction, test):
        before = await self.game.read()
        await self.game.press(direction)
        after = await self.game.read()
        name = DIRECTION_NAMES[direction]

        expected, gained, moved = ref.move(before["board"], direction)
        self.say("  move %-5s score %3d -> %-3d  %s  =>  %s"
                 % (name, before["score"], after["score"],
                    fmt_board(before["board"]), fmt_board(after["board"])))

        if not moved:
            self.check(after["board"] == before["board"], test, "no_op_changed",
                       direction_name=name, before=before["board"], after=after["board"])
            self.check(after["score"] == before["score"], test, "score_mismatch",
                       direction_name=name, actual_delta=after["score"] - before["score"],
                       expected_delta=0)
            self.check([t["isNew"] for t in after["tiles"]] == [t["isNew"] for t in before["tiles"]],
                       test, "spawn_count", direction_name=name,
                       spawned=sum(1 for t in after["tiles"] if t["isNew"]))
        else:
            self.check(after["score"] - before["score"] == gained, test, "score_mismatch",
                       direction_name=name, actual_delta=after["score"] - before["score"],
                       expected_delta=gained)
            extra = diff_cells(expected, after["board"])
            spawned = [(r, c, actual) for r, c, exp, actual in extra if exp == 0]
            others = [(r, c, actual) for r, c, exp, actual in extra if exp != 0]
            self.check(len(others) == 0, test, "board_mismatch", direction_name=name,
                       expected=expected, actual=after["board"])
            self.check(len(spawned) == 1, test, "spawn_count", direction_name=name,
                       spawned=len(spawned))
            self.check(all(v in (2, 4) for _, _, v in spawned), test, "spawn_value",
                       direction_name=name, value=spawned[0][2] if spawned else -1)
            self.check(sum(1 for t in after["tiles"] if t["isNew"]) == 1, test, "spawn_count",
                       direction_name=name,
                       spawned=sum(1 for t in after["tiles"] if t["isNew"]))

        self.invariants(after, test)
        return after

    async def random_play(self, plies, rng):
        await self.game.restart()
        for i in range(plies):
            direction = rng.randrange(4)
            snap = await self.check_move(direction, "random_play[%d]" % i)
            if not ref.moves_available(snap["board"]):
                await self.game.restart()
        return await self.game.read()

    # ------------------------------------------------------------------ scenarios

    async def restart_scenario(self):
        await self.random_play(12, random.Random(11))
        before = await self.game.read()
        await self.game.restart()
        after = await self.game.read()
        self.check(tile_count(after["board"]) == 2, "restart", "restart_residue",
                   tiles=tile_count(after["board"]), score=after["score"])
        self.check(after["score"] == 0, "restart", "restart_residue",
                   tiles=tile_count(after["board"]), score=after["score"])
        self.check(not after["messageVisible"], "restart", "message_wrong",
                   message=after["visibleMessage"])
        self.check(after["best"] >= before["best"], "restart", "best_regressed",
                   after_best=after["best"], before_best=before["best"])
        self.check(after["modelBoard"] == after["board"], "restart", "dom_model_mismatch",
                   model=after["modelBoard"] or [], dom=after["board"])
        return after

    async def persistence_scenario(self):
        await self.game.restart()
        rng = random.Random(29)
        for _ in range(6):
            await self.game.press(rng.randrange(4))
        before = await self.game.read()
        await self.game.reload()
        after = await self.game.read()
        self.check(after["board"] == before["board"], "persistence", "persistence_board",
                   actual=after["board"], expected=before["board"])
        self.check(after["score"] == before["score"], "persistence", "persistence_score",
                   actual=after["score"], expected=before["score"])
        self.check(int(after["bestScore"] or 0) == before["best"], "persistence",
                   "persistence_score", actual=int(after["bestScore"] or 0), expected=before["best"])
        self.invariants(after, "persistence")
        return before, after

    async def game_over_scenario(self):
        await self.game.seed(GameClient.state_from_board(DEAD_NEXT_MOVE, score=100), best_score=100)
        before = await self.game.read()
        self.check(before["board"] == DEAD_NEXT_MOVE, "game_over", "persistence_board",
                   actual=before["board"], expected=DEAD_NEXT_MOVE)

        snap = await self.check_move(3, "game_over")  # the single legal merge
        self.check("game-over" in snap["messageClass"] and snap["messageVisible"],
                   "game_over", "message_missing")
        self.check(snap["messageText"] == "Game over!" and snap["messageVisible"],
                   "game_over", "message_missing")
        self.check(snap["score"] == 104, "game_over", "score_mismatch", direction_name="left",
                   actual_delta=snap["score"], expected_delta=104)
        self.check(snap["gameState"] is None, "game_over", "state_not_cleared")

        # A terminated game must ignore further input entirely.
        frozen = await self.game.read()
        await self.game.press(0)
        after = await self.game.read()
        self.check(after["board"] == frozen["board"], "game_over_ignores_input",
                   "no_op_changed", direction_name="up", before=frozen["board"], after=after["board"])
        return snap

    async def win_scenario(self):
        await self.game.seed(GameClient.state_from_board(WIN_NEXT_MOVE, score=0), best_score=0)
        snap = await self.check_move(3, "win")
        self.check("game-won" in snap["messageClass"] and snap["messageVisible"],
                   "win", "message_missing")
        self.check(snap["messageText"] == "You win!" and snap["messageVisible"],
                   "win", "message_missing")
        self.check(snap["hasKeepPlaying"], "win", "message_missing")
        self.check(snap["score"] == 2048, "win", "score_mismatch", direction_name="left",
                   actual_delta=snap["score"], expected_delta=2048)
        expected_board, _, _ = ref.move(WIN_NEXT_MOVE, 3)
        self.check(2048 in [v for row in snap["board"] for v in row], "win", "board_mismatch",
                   direction_name="left", expected=expected_board, actual=snap["board"])

        await self.game.click(".keep-playing-button")
        await asyncio.sleep(0.2)
        resumed = await self.game.read()
        self.check(not resumed["messageVisible"], "keep_playing", "message_wrong",
                   message=resumed["visibleMessage"])

        # After Keep going the game must accept input again.
        for direction in (2, 3, 0, 1):
            probe = await self.check_move(direction, "keep_playing")
            if probe["board"] != resumed["board"]:
                break
        else:
            self.check(False, "keep_playing", "keep_playing_blocked")
        return snap

    # ------------------------------------------------------------------ Laya layer

    async def judge_messages(self, snap, test):
        moves_possible = ref.moves_available(snap["board"])
        largest = max([v for row in snap["board"] for v in row] or [0])
        message = snap["visibleMessage"]
        if message == "You win!":
            correct = largest >= 2048
        elif message == "Game over!":
            correct = not moves_possible
        else:
            correct = moves_possible
        expected = "matches" if correct else "contradicts"
        verdict = laya_judge.judge_message(self.laya, snap, moves_possible, message)
        self.message_checks.append({
            "test": test,
            "message": message,
            "moves_possible": moves_possible,
            "largest": largest,
            "deterministic": expected,
            "laya": verdict["verdict"],
            "probabilities": verdict["probabilities"],
            "agree": verdict["verdict"] == expected,
        })

    async def triage_failures(self):
        for failure in self.failures:
            failure["laya"] = laya_judge.triage(self.laya, failure["evidence"])

    # ------------------------------------------------------------------ driver

    async def run(self, plies=40, seed=2048, judge=True):
        rng = random.Random(seed)
        await self.game.restart()
        self.say("\n== random play, %d plies, seed %d ==" % (plies, seed))
        await self.random_play(plies, rng)
        self.say("\n== restart (New Game button) ==")
        await self.restart_scenario()
        self.say("\n== persistence across reload ==")
        await self.persistence_scenario()
        self.say("\n== game over: one merge away from a dead board ==")
        over = await self.game_over_scenario()
        self.say("\n== win: two 1024 tiles merge into 2048, then Keep going ==")
        win = await self.win_scenario()

        if self.laya is not None and judge:
            await self.judge_messages(over, "game_over")
            await self.judge_messages(win, "win")
            await self.triage_failures()

        return {
            "seed": seed,
            "plies": plies,
            "checks": self.checks,
            "failed": len(self.failures),
            "passed": self.checks - len(self.failures),
            "failures": self.failures,
            "laya_message_checks": self.message_checks,
        }


class PlaywrightTab:
    """Adapts a Playwright page to the small surface GameClient needs."""

    def __init__(self, page):
        self.page = page

    async def evaluate(self, js):
        return await self.page.evaluate(js)

    async def press(self, key):
        await self.page.keyboard.press(key)

    async def goto(self, url):
        await self.page.goto(url, wait_until="load")


def free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def mutation_run(make_client, base_url, laya, plies, seed):
    """Run the suite against every mutant and report detection + Laya triage accuracy.

    `make_client(url)` returns a ready GameClient, so the same routine drives either a
    Playwright page or any other tab implementation.
    """
    import mutants

    results = {}
    for name in mutants.MUTATIONS:
        url = "%s/%s/index.html" % (base_url.rstrip("/"), name)
        game = make_client(url)
        await game.reload()
        report = await Suite(game, laya).run(plies=plies, seed=seed, judge=laya is not None)
        labels = [f["laya"]["subsystem"] for f in report["failures"] if f.get("laya")]
        hits = sum(1 for label in labels if label == name)
        results[name] = {
            "detected": report["failed"] > 0,
            "checks": report["checks"],
            "failed": report["failed"],
            "failure_kinds": sorted({f["kind"] for f in report["failures"]}),
            "laya_labels": {label: labels.count(label) for label in sorted(set(labels))},
            "laya_top_label": max(set(labels), key=labels.count) if labels else None,
            "laya_correct_fraction": round(hits / len(labels), 3) if labels else None,
        }
    return results


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8792/index.html")
    parser.add_argument("--plies", type=int, default=40)
    parser.add_argument("--seed", type=int, default=2048)
    parser.add_argument("--no-laya", action="store_true")
    parser.add_argument("--trace", action="store_true",
                        help="print every move and every assertion as it happens")
    parser.add_argument("--mutants", action="store_true",
                        help="build mutated copies of the game and require the suite to fail on each")
    args = parser.parse_args()

    from playwright.async_api import async_playwright

    laya = None
    if not args.no_laya:
        from laya_client import LayaClient
        laya = LayaClient()

    server = None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()

            if args.mutants:
                import subprocess
                import tempfile
                import mutants

                tree = mutants.build_mutant_tree(pathlib.Path(tempfile.mkdtemp(prefix="2048-mutants-"))
                                                 / "site")
                port = free_port()
                server = subprocess.Popen(
                    [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                     "--directory", str(tree)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                await asyncio.sleep(0.6)
                results = await mutation_run(
                    lambda url: GameClient(PlaywrightTab(page), url=url),
                    "http://127.0.0.1:%d" % port, laya, args.plies, args.seed)
                await browser.close()
                print(json.dumps(results, indent=2, default=str))
                missed = [n for n, r in results.items() if not r["detected"]]
                if missed:
                    print("UNDETECTED MUTANTS: %s" % ", ".join(missed), file=sys.stderr)
                return 0 if not missed else 1

            await page.goto(args.url, wait_until="load")
            suite = Suite(GameClient(PlaywrightTab(page), url=args.url), laya, trace=args.trace)
            report = await suite.run(plies=args.plies, seed=args.seed)
            await browser.close()
    finally:
        if server is not None:
            server.terminate()

    print(json.dumps(report, indent=2, default=str))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
