"""Let jev play 2048 in a browser the user can watch.

Connects to an already-running Chrome over CDP (so the window is real and visible),
reuses the tab that already shows the game, and plays one move at a time with a pause
between moves. Prints every decision so the terminal and the window agree.

Usage:
  /tmp/pwenv/bin/python jev-test/watch.py --cdp http://127.0.0.1:9222 --max-moves 100
"""

import argparse
import asyncio
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "laya-test"))

import game_client  # noqa: E402
import reference2048 as ref  # noqa: E402
from run_tests import PlaywrightTab  # noqa: E402

from jev_client import JevClient  # noqa: E402

NAMES = ("up", "right", "down", "left")


def render(board):
    width = max(len(str(v)) for row in board for v in row) or 1
    return " | ".join(" ".join(str(v).rjust(width) if v else ".".rjust(width) for v in row)
                      for row in board)


async def pick_page(browser, url):
    for context in browser.contexts:
        for page in context.pages:
            if page.url.startswith(url.rsplit("/", 1)[0]):
                return page
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    return await context.new_page()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--url", default="http://127.0.0.1:8792/index.html")
    parser.add_argument("--prompt", default="neutral", choices=["neutral", "hinted"])
    parser.add_argument("--max-moves", type=int, default=120)
    parser.add_argument("--delay", type=float, default=0.7, help="pause between moves, seconds")
    parser.add_argument("--new-game", action="store_true", help="click New Game first")
    args = parser.parse_args()

    from playwright.async_api import async_playwright

    jev = JevClient(prompt=args.prompt)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(args.cdp)
        page = await pick_page(browser, args.url)
        await page.bring_to_front()
        if not page.url.startswith(args.url.rsplit("/", 1)[0]):
            await page.goto(args.url, wait_until="load")

        client = game_client.GameClient(PlaywrightTab(page), url=args.url,
                                        settle_seconds=0.08, poll_interval=0.03)
        if args.new_game:
            await client.restart()
        await asyncio.sleep(0.4)

        history = []
        moves = 0
        decisions = 0
        forced = 0
        latencies = []
        started = time.perf_counter()

        while moves < args.max_moves:
            snap = await client.read()
            board = snap["board"]

            if snap["messageVisible"] and "game-won" in snap["messageClass"]:
                print("*** 2048 reached — clicking Keep going ***", flush=True)
                await client.click(".keep-playing-button")
                snap = await client.read()
                board = snap["board"]

            if not ref.moves_available(board):
                print("*** GAME OVER ***", flush=True)
                break

            legal = [name for index, name in enumerate(NAMES) if ref.move(board, index)[2]]
            if not legal:
                print("*** GAME OVER (no legal move) ***", flush=True)
                break

            if len(legal) == 1:
                name = legal[0]
                forced += 1
                latency = 0
            else:
                decision = jev.choose(board, snap["score"], ref.winning_tile(board), legal, history)
                name = decision["name"]
                decisions += 1
                latency = decision["latency_ms"]
                latencies.append(latency)

            before_score = snap["score"]
            await client.press(NAMES.index(name))
            after = await client.read()
            moves += 1
            history.append(name)

            print("%3d  %-5s  score %5d -> %-5d  max %4d  %s  [%s%s]" % (
                moves, name, before_score, after["score"], ref.winning_tile(after["board"]),
                render(after["board"]),
                "forced" if latency == 0 else "jev %dms" % latency,
                "" if latency == 0 else " p=%.2f" % max(decision["probabilities"].values()),
            ), flush=True)

            await asyncio.sleep(args.delay)

        final = await client.read()
        elapsed = time.perf_counter() - started
        print("\n=== jev 本局结束 ===")
        print("moves=%d  score=%d  max_tile=%d" % (
            moves, final["score"], ref.winning_tile(final["board"])))
        print("jev decisions=%d  forced=%d  api_median=%sms  wall=%.1fs" % (
            decisions, forced,
            round(sorted(latencies)[len(latencies) // 2]) if latencies else None, elapsed))
        # Deliberately no browser.close(): this connection was adopted over CDP, so closing
        # it would terminate the user's own Chrome window instead of just disconnecting.


if __name__ == "__main__":
    asyncio.run(main())
