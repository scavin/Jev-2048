"""The black-box page adapter: read the board, press a direction, restart.

`game-test/game_client.py` already owns the hard part — reading a settled board out of a
mid-animation DOM, and clicking the game's own restart anchor through a real pointer
sequence. This module only adds what the experiment needs on top: deterministic seeded
starts, a wait for the page to actually react to a key, and screenshots.
"""

import asyncio
import time

import labpaths  # noqa: F401

from game.simulator import DIRECTION_INDEX
from game.state import Observation, from_snapshot

import game_client
from game_client import DIRECTION_NAMES, GameClient

KEYS = {name: game_client.DIRECTIONS[index] for name, index in DIRECTION_INDEX.items()}


def seeded_url(url, seed):
    """The game ignores query strings; the RNG shim installed by the browser session
    reads `seed` from here, so every navigation restarts the spawn stream from scratch."""
    return "%s%sseed=%d" % (url, "&" if "?" in url else "?", seed)


class GameAdapter:
    """One live 2048 tab, with the experiment's timing knobs."""

    def __init__(self, tab, url=None, change_timeout=0.35, poll_interval=0.02,
                 poll_timeout=3.0):
        self.tab = tab
        self.base_url = url or labpaths.GAME_URL
        self.change_timeout = change_timeout
        self.client = GameClient(tab, url=self.base_url, settle_seconds=0.0,
                                 poll_interval=poll_interval, poll_timeout=poll_timeout)
        self.current = None
        self.notes = []

    async def open(self, seed, attempts=5):
        """Navigate to a fresh game whose spawn stream is fully determined by `seed`.

        One navigation is enough: the browser session's init script clears the page's saved
        game and reseeds `Math.random` before the game's scripts run, so this load always
        deals a fresh pair of start tiles from the beginning of the stream.

        The board renders inside a `requestAnimationFrame`, so an immediate read sees an
        empty page and the stability poll happily agrees with itself. Waiting for the start
        tiles is the honest readiness condition. A page that loads but never deals its tiles
        is retried, because the navigation is deterministic: the retry reaches the same game,
        so a retry cannot make results depend on luck. The last failure is re-raised with the
        page's own errors attached.
        """
        url = seeded_url(self.base_url, seed)
        self.client.url = url
        failure = None
        for attempt in range(attempts):
            await self.tab.goto(url)
            try:
                self.current = await self._await_start()
                return self.current
            except RuntimeError as exc:
                failure = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * 2 ** attempt)
        raise failure

    async def _await_start(self, timeout=10.0):
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        observation = await self.observe()
        while loop.time() < deadline:
            if any(v for row in observation.board for v in row):
                return observation
            lost = getattr(self.tab, "failed_assets", [])
            if lost:
                # The page lost one of its own scripts, so nothing will ever appear here.
                # Fail now and let `open` reload instead of waiting out the timeout.
                raise RuntimeError("the page lost %d asset(s): %r" % (len(lost), lost[:3]))
            if not await self._booted():
                raise RuntimeError("the page loaded without the game's scripts")
            broken = [item for item in getattr(self.tab, "errors", [])
                      if item.startswith("pageerror:")]
            if broken:
                # The game threw while booting. It will not recover on this load.
                raise RuntimeError("the page threw while starting: %s" % broken[0][:200])
            await asyncio.sleep(0.05)
            observation = await self.observe()
        diagnostics = await self.tab.evaluate(
            "(() => ({url: location.href, ready: document.readyState,"
            " tiles: document.querySelectorAll('.tile-container .tile').length,"
            " scripts: document.scripts.length,"
            " visible: document.visibilityState,"
            " frameShim: window.requestAnimationFrame.toString().includes('timers'),"
            " stored: localStorage.getItem('gameState') !== null}))()")
        diagnostics["page_errors"] = list(getattr(self.tab, "errors", []))[-5:]
        raise RuntimeError("the game never rendered its start tiles after %.0fs: %r (%r)"
                           % (timeout, observation.board, diagnostics))

    async def _booted(self):
        """Whether the game's own constructor exists — a readiness probe, not a state read."""
        return await self.tab.evaluate("typeof GameManager !== 'undefined'")

    async def observe(self, timeout=3.0):
        """Read until the board is well formed, then return it.

        `GameClient.read()` already waits for two agreeing snapshots. The poll interval is
        set above one animation frame, so two agreeing reads cannot both be the pre-render
        position of a tile that moved; agreement therefore means the frame has settled.
        A board that still contains an unreadable cell is retried rather than reported.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            started = time.perf_counter()
            snap = await self.client.read()
            observation = from_snapshot(snap, read_ms=(time.perf_counter() - started) * 1000)
            if observation.well_formed or loop.time() >= deadline:
                break
            await asyncio.sleep(self.client.poll_interval)
        if not observation.well_formed:
            raise RuntimeError("unreadable board after %.1fs: %r"
                               % (timeout, observation.board))
        if observation.source_note:
            self.notes.append(observation.source_note)
        self.current = observation
        return observation

    async def _wait_for_change(self, previous_key, timeout):
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            await asyncio.sleep(self.client.poll_interval)
            snap = await self.client.read_once()
            if game_client.state_key(snap) != previous_key:
                return True
        return False

    async def apply(self, direction, previous=None):
        """Press one direction and return the settled board that follows.

        The key is sent first and the page is then polled until it actually reacts, so a
        fast machine does not pay a fixed sleep and a slow one does not read mid-animation.
        A direction the game ignores never changes the page, so that wait times out and the
        stable read that follows reports the unchanged board — which is the honest record
        of what happened.
        """
        previous = previous or self.current or await self.observe()
        previous_key = game_client.state_key(await self.client.read_once())
        started = time.perf_counter()
        await self.tab.press(KEYS[direction])
        reacted = await self._wait_for_change(previous_key, self.change_timeout)
        after = await self.observe()
        return after, {
            "wall_ms": round((time.perf_counter() - started) * 1000, 1),
            "page_reacted": reacted,
        }

    async def restart(self):
        await self.client.restart()
        self.current = await self.observe()
        return self.current

    async def keep_playing(self):
        """Dismiss the win message. This is a harness action, never a jev decision."""
        await self.client.click(".keep-playing-button")
        await asyncio.sleep(0.05)
        self.current = await self.observe()
        return self.current

    async def screenshot(self, path, quality=70, timeout=2.0):
        """Capture the window for the dashboard.

        A headed window that is occluded or backgrounded can stall the compositor, and a
        screenshot that waits for a frame would then stall the whole game. The timeout is
        what keeps a cosmetic feature off the critical path.
        """
        page = getattr(self.tab, "page", None)
        if page is None:
            return False
        await page.screenshot(path=path, type="jpeg", quality=quality,
                              timeout=timeout * 1000)
        return True

    def summarise(self, observation: Observation):
        return {
            "board": observation.rows(),
            "score": observation.score,
            "best": observation.best,
            "max_tile": observation.max_tile,
            "empty_cells": observation.empty_cells,
            "message": observation.message,
            "board_hash": observation.board_hash,
        }


__all__ = ["GameAdapter", "KEYS", "DIRECTION_NAMES", "seeded_url"]
