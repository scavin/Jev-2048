"""Black-box client for the running 2048 page.

Everything this module observes comes from outside the game's own code: the rendered
DOM and the localStorage the page itself writes. No game internals are imported, so a
bug in GameManager cannot hide behind the harness reading the same object graph.

The tab is duck-typed: any object exposing `evaluate(js_string)`, `press(key)` and
`reload()` works, which keeps the driver (an agent browser, Playwright, CDP) swappable.
"""

import asyncio
import json

DIRECTIONS = {0: "ArrowUp", 1: "ArrowRight", 2: "ArrowDown", 3: "ArrowLeft"}
DIRECTION_NAMES = {0: "up", 1: "right", 2: "down", 3: "left"}

# Runs as a page-global expression: reads the rendered board and the page's own storage.
READ_JS = r"""
(() => {
  const classes = el => el.className.split(/\s+/).filter(Boolean);
  const tiles = [...document.querySelectorAll('.tile-container .tile')].map(el => {
    const cls = classes(el);
    const pos = cls.find(c => /^tile-position-[0-9]-[0-9]$/.test(c));
    const val = cls.find(c => /^tile-[0-9]+$/.test(c));
    const m = pos ? pos.match(/^tile-position-([0-9])-([0-9])$/) : null;
    return {
      x: m ? Number(m[1]) : null,
      y: m ? Number(m[2]) : null,
      value: val ? Number(val.slice(5)) : null,
      merged: cls.includes('tile-merged'),
      isNew: cls.includes('tile-new'),
      inner: el.querySelector('.tile-inner') ? el.querySelector('.tile-inner').textContent : null
    };
  });
  const raw = localStorage.getItem('gameState');
  return {
    tiles: tiles,
    scoreText: document.querySelector('.score-container').textContent,
    bestText: document.querySelector('.best-container').textContent,
    messageClass: document.querySelector('.game-message').className,
    messageVisible: getComputedStyle(document.querySelector('.game-message')).display !== 'none',
    messageText: document.querySelector('.game-message p').textContent,
    hasKeepPlaying: !!document.querySelector('.keep-playing-button'),
    gameState: raw ? JSON.parse(raw) : null,
    bestScore: localStorage.getItem('bestScore'),
    gridCells: document.querySelectorAll('.grid-container .grid-cell').length
  };
})()
"""


def board_from_tiles(tiles):
    """Recover the 4x4 board from rendered tiles.

    The actuator renders a merged tile plus both of its consumed sources, and the sources
    animate into the merge cell, so a cell that merged holds three elements. The merged
    element is the authoritative one; a cell without one holds exactly one element.
    """
    board = [[0] * 4 for _ in range(4)]
    occupied = {}
    for tile in tiles:
        if tile["x"] is None or tile["value"] is None:
            continue
        cell = (tile["y"] - 1, tile["x"] - 1)
        occupied.setdefault(cell, []).append(tile)

    for (r, c), group in occupied.items():
        merged = [t for t in group if t["merged"]]
        if merged:
            board[r][c] = merged[0]["value"]
        elif len(group) == 1:
            board[r][c] = group[0]["value"]
        else:
            # No merge marker but several elements: report the ambiguity rather than guess.
            board[r][c] = -1
    return board


def board_from_model(game_state):
    """The board as the page serialized it into localStorage."""
    board = [[0] * 4 for _ in range(4)]
    if not game_state:
        return None
    cells = game_state["grid"]["cells"]
    for x, column in enumerate(cells):
        for y, cell in enumerate(column):
            if cell:
                board[y][x] = cell["value"]
    return board


CLICK_JS = r"""
(selector => {
  const el = document.querySelector(selector);
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const at = { bubbles: true, cancelable: true, composed: true,
               clientX: r.x + r.width / 2, clientY: r.y + r.height / 2, button: 0, buttons: 1 };
  el.dispatchEvent(new PointerEvent('pointerdown', at));
  el.dispatchEvent(new MouseEvent('mousedown', at));
  el.dispatchEvent(new PointerEvent('pointerup', at));
  el.dispatchEvent(new MouseEvent('mouseup', at));
  el.dispatchEvent(new MouseEvent('click', at));
  return true;
})(%s)
"""


def state_key(snap):
    """The parts of a snapshot that a player can observe, for stability comparison."""
    return (tuple(map(tuple, snap["board"])),
            tuple(map(tuple, snap["modelBoard"] or [])),
            snap["score"], snap["best"], snap["messageVisible"], snap["messageText"],
            tuple((t["x"], t["y"], t["value"], t["merged"], t["isNew"]) for t in snap["tiles"]))


class GameClient:
    def __init__(self, tab, url=None, settle_seconds=0.2, poll_interval=0.06, poll_timeout=4.0):
        self.tab = tab
        self.url = url
        self.settle_seconds = settle_seconds
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    async def _settle(self, extra=0.0):
        # Let the input reach the page before the first read of the stability poll.
        await asyncio.sleep(self.settle_seconds + extra)

    async def read_once(self):
        raw = await self.tab.evaluate(READ_JS)
        if isinstance(raw, str):
            raw = json.loads(raw)
        raw["board"] = board_from_tiles(raw["tiles"])
        raw["modelBoard"] = board_from_model(raw["gameState"])
        raw["score"] = int(raw["scoreText"].split("+")[0].strip() or 0)
        raw["best"] = int(raw["bestText"].strip() or 0)
        # clearMessage() only drops the game-won/game-over class; the <p> keeps its text.
        # Visibility, not textContent, is what a player observes.
        raw["visibleMessage"] = raw["messageText"] if raw["messageVisible"] else ""
        return raw

    async def read(self):
        """Read until two consecutive snapshots agree.

        actuate() renders inside requestAnimationFrame and moves tile positions one frame
        later, so any single read can land mid-animation. Sleeping a fixed amount is a guess
        about frame timing; polling until the observed state stops changing is not.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.poll_timeout
        previous = await self.read_once()
        while loop.time() < deadline:
            await asyncio.sleep(self.poll_interval)
            current = await self.read_once()
            if state_key(current) == state_key(previous):
                return current
            previous = current
        return previous

    async def press(self, direction, settle=True):
        await self.tab.press(DIRECTIONS[direction])
        if settle:
            await self._settle()

    async def click(self, selector):
        """Click through a full pointer sequence at the element's centre.

        The tab's own click helper resolves elements through the accessibility tree, which
        never sees the game's bare `<a class="restart-button">`. Dispatching the pointer
        sequence keeps the real event pipeline (bubbling, coordinates, the game's own
        click listener) in the loop.
        """
        clicked = await self.tab.evaluate(CLICK_JS % json.dumps(selector))
        if not clicked:
            raise RuntimeError("no element matches %r" % selector)

    async def restart(self):
        await self.click(".restart-button")
        await self._settle()

    async def reload(self):
        if not self.url:
            raise RuntimeError("GameClient needs the page url to reload it")
        await self.tab.goto(self.url)
        await self._settle(0.3)

    async def seed(self, game_state, best_score=None, clear=False):
        """Install a board through the page's own persistence contract, then reload.

        This is how a specific board (dead, winnable, mid-game) is reached without
        playing thousands of random moves.
        """
        payload = json.dumps(game_state)
        best = "null" if best_score is None else str(best_score)
        await self.tab.evaluate(
            "(() => { %s localStorage.setItem('gameState', %s); localStorage.setItem('bestScore', %s); return true; })()"
            % ("localStorage.clear();" if clear else "", json.dumps(payload), best)
        )
        await self.reload()

    @staticmethod
    def state_from_board(board, score=0, over=False, won=False, keep_playing=False):
        cells = [[None] * 4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                if board[r][c]:
                    # Grid stores cells[x][y]; position must agree with the index it sits at.
                    cells[c][r] = {"position": {"x": c, "y": r}, "value": board[r][c]}
        return {"grid": {"size": 4, "cells": cells}, "score": score, "over": over,
                "won": won, "keepPlaying": keep_playing}
