"""Single game, visible browser, live dashboard, human controls.

This is the demo path: one game at a time in a real window, every step published to
`ui/live_state.json` for the dashboard and mirrored to the terminal, with Start / Pause /
Step / Reset / Speed handled by polling `ui/control.json`.

The control channel is deliberately one-directional. The dashboard writes commands; this
runner only reads them and never writes back, so a `Step` click cannot be double-counted
by two processes racing on the same counter.
"""

import asyncio
import json
import os
import subprocess
import sys
import time

import labpaths  # noqa: F401

from game.adapter import GameAdapter
from players import build
from players.base import Decision
from runner.browser import BrowserSession
from runner.game_loop import GameRunner, Hook, LogWriter

CONTROL_PATH = os.path.join(labpaths.UI_DIR, "control.json")
STATE_PATH = os.path.join(labpaths.UI_DIR, "live_state.json")
SHOT_PATH = os.path.join(labpaths.UI_DIR, "live.jpg")

# Seconds to wait between moves. "max" runs as fast as the page and the model allow.
SPEEDS = {"1": 1.2, "5": 0.24, "20": 0.06, "max": 0.0}

ARROWS = {"up": "↑", "down": "↓", "left": "←", "right": "→"}
DIRECTIONS = tuple(ARROWS)


class ResetRequested(Exception):
    """The human asked for a fresh game. The runner starts one; nothing else changes."""


def new_control_state():
    """Shared across games: last obeyed command, pause flag, steps released, human moves."""
    return {"seq": -1, "paused": False, "consumed": 0, "manual": False, "moves_done": 0}


def write_json_atomic(path, payload):
    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        json.dump(payload, handle, default=str)
    os.replace(temporary, path)


def read_json(path, default=None):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def format_decision(live):
    probabilities = live.get("probabilities")
    if not probabilities:
        return "%s  (no probabilities returned)" % str(live.get("chosen")).upper()
    parts = " ".join("%s %.2f" % (name.upper(), value)
                     for name, value in sorted(probabilities.items(), key=lambda kv: -kv[1]))
    return "%s  %s" % (str(live.get("chosen")).upper(), parts)


class InteractiveHook(Hook):
    """Gate the loop on human controls and publish the live state every step.

    `control` is shared across games on purpose. It carries the last command sequence number
    the runner has already obeyed, so a `reset` is acted on once instead of restarting the
    game forever, and it carries the pause state, so a reset does not silently resume.
    """

    def __init__(self, adapter, mode, seed, speed="5", control_path=CONTROL_PATH,
                 state_path=STATE_PATH, shot_path=SHOT_PATH, screenshot_interval=0.2,
                 echo=True, control=None, panel=True, shots=True):
        self.adapter = adapter
        self.mode = mode
        self.seed = seed
        self.speed = speed if speed in SPEEDS else "5"
        self.control_path = control_path
        self.state_path = state_path
        self.shot_path = shot_path
        self.screenshot_interval = screenshot_interval
        self.echo = echo
        # With no dashboard nobody reads the state file or the screenshot, and a headed
        # screenshot costs about a tenth of a second per step.
        self.panel = panel
        # Capturing a visible window forces the compositor to re-raster it, which reads as the
        # whole window flashing — once per publish, and publishes happen either side of every
        # move. When a human is watching the window there is nothing to mirror, so the panel
        # draws the board from the data instead and no surface is ever captured.
        self.shots = shots
        self.control = control if control is not None else new_control_state()
        self.last_shot = 0.0
        self.screenshot_failures = 0
        self.outcome = None
        # The live payload of the step in progress, so a wait for a human move can keep the
        # panel fresh instead of leaving it frozen on the moment the wait began.
        self._live = None

    @property
    def paused(self):
        return self.control["paused"]

    @property
    def manual(self):
        return self.control["manual"]

    # ------------------------------------------------------------------ control

    def _apply_control(self):
        control = read_json(self.control_path)
        if not control:
            return
        # The direction source is a level, not a one-shot, so it is read even when no new
        # command arrived.
        if isinstance(control.get("manual"), bool):
            self.control["manual"] = control["manual"]
        seq = int(control.get("seq", 0))
        if seq > self.control["seq"]:
            self.control["seq"] = seq
            command = control.get("command")
            if command == "run":
                self.control["paused"] = False
            elif command == "pause":
                self.control["paused"] = True
            elif command == "reset":
                raise ResetRequested()
            if control.get("speed") in SPEEDS:
                self.speed = control["speed"]

    def _take_human_move(self):
        """The oldest direction the human has not played yet, or None.

        The panel appends to a queue with a monotonic `seq`. The highest one this runner has
        executed is carried across games, so a queued move is played exactly once and a
        restart never replays one.
        """
        control = read_json(self.control_path) or {}
        queued = control.get("moves")
        if not isinstance(queued, list):
            return None
        waiting = sorted((move for move in queued
                          if isinstance(move, dict) and move.get("direction") in DIRECTIONS
                          and int(move.get("seq", 0)) > self.control["moves_done"]),
                         key=lambda move: int(move.get("seq", 0)))
        if not waiting:
            return None
        self.control["moves_done"] = int(waiting[0]["seq"])
        return waiting[0]["direction"]

    async def choose(self, ctx):
        """Take the next move from the human while the panel is in manual mode.

        None hands the decision back to the policy, which is what every other run gets. While
        waiting, the panel keeps being refreshed so it shows a live "waiting for you" state.
        """
        if not self.panel:
            return None
        self._apply_control()
        if not self.manual:
            return None
        live = self._live if self._live is not None else {}
        live.update(manual=True, status="waiting for you", chosen=None, probabilities=None,
                    latency_ms=0.0)
        await self.publish(live)
        ticks = 0
        while True:
            direction = self._take_human_move()
            if direction is not None:
                return Decision(name=direction, source="human")
            self._apply_control()
            if not self.manual:
                return None
            await asyncio.sleep(0.1)
            ticks += 1
            if ticks % 5 == 0:
                await self.publish(live)

    async def _gate(self, live):
        """Block while paused, releasing exactly one step per pending step budget.

        While blocked the panel keeps being refreshed, so a human stepping through a single
        decision sees a live `paused` state instead of the file frozen at the moment the
        pause began.
        """
        if not self.panel:
            return
        self._apply_control()
        if not self.paused:
            return
        live.update(paused=True, speed=self.speed, step_mode=True, status="paused")
        await self.publish(live)
        ticks = 0
        while True:
            control = read_json(self.control_path) or {}
            if self.control["consumed"] < int(control.get("pending_steps", 0)):
                self.control["consumed"] += 1
                return
            await asyncio.sleep(0.1)
            self._apply_control()
            if not self.paused:
                # Resumed. The budget is not the only way out of a pause.
                return
            ticks += 1
            if ticks % 5 == 0:
                await self.publish(live)

    # ------------------------------------------------------------------ hooks

    async def before_step(self, live):
        self._live = live
        await self._gate(live)
        live.update(paused=self.paused, speed=self.speed, step_mode=self.paused,
                    status="paused" if self.paused else "deciding")
        await self.publish(live)

    async def after_step(self, live):
        await self.publish(live)
        if self.echo:
            print("  %4d  %-6s score %-6d max %-5d empty %-2d  %s  (%.0f ms)"
                  % (live["step"], live["chosen"], live["score"], live["max_tile"],
                     live["empty_cells"], format_decision(live), live["latency_ms"]),
                  flush=True)
            tags = live.get("failure_tags") or []
            if tags:
                print("        tagged: %s" % ", ".join(tags), flush=True)
        if SPEEDS[self.speed]:
            await asyncio.sleep(SPEEDS[self.speed])

    async def on_end(self, live, outcome):
        self.outcome = outcome
        await self.publish(live)
        if self.echo:
            print("\n  game %d finished: %s after %d moves, score %d, max tile %d"
                  % (outcome.game_id, outcome.ended, outcome.steps, outcome.score,
                     outcome.max_tile), flush=True)

    # ------------------------------------------------------------------ publishing

    async def publish(self, live):
        if not self.panel:
            return
        payload = dict(live)
        payload.update(paused=self.paused, speed=self.speed, step_mode=self.paused,
                       shots=self.shots, manual=self.manual,
                       moves_done=self.control["moves_done"], updated_at=time.time())
        write_json_atomic(self.state_path, payload)
        await self._maybe_screenshot()

    async def _maybe_screenshot(self):
        if not self.shots:
            return
        now = time.time()
        if now - self.last_shot < self.screenshot_interval:
            return
        self.last_shot = now
        try:
            await self.adapter.screenshot(self.shot_path)
            self.screenshot_failures = 0
        except Exception as exc:  # a cosmetic panel must never slow the experiment down
            self.screenshot_failures += 1
            if self.screenshot_failures in (1, 5, 20):
                print("  (screenshot skipped: %s)" % exc, flush=True)
            self.screenshot_interval = min(self.screenshot_interval * 2, 5.0)


async def play_interactive(adapter, mode, seed, game_id, max_steps, log, hook):
    await adapter.open(seed)
    runner = GameRunner(adapter, build(mode, seed=seed), mode, game_id, seed,
                        max_steps=max_steps, hook=hook, log=log)
    return await runner.play()


def browser_gone(adapter):
    """Whether the human closed the window out from under us."""
    page = getattr(getattr(adapter, "tab", None), "page", None)
    if page is None:
        return True
    try:
        return page.is_closed()
    except Exception:
        return True


async def run_interactive(mode, seed=2048, games=1, max_steps=5000, log_path=None,
                          cdp=None, headless=False, speed="5", dashboard=True,
                          dashboard_port=8799, echo=True, open_dashboard=True,
                          on_outcome=None, between_games=0.0, keep=200,
                          shot_interval=0.2, shots=None):
    """Play games in a real window, one after another, under human control.

    `mode` is one mode name or a sequence of them; a sequence is used round-robin, one per
    game, which is what makes the contrast between state designs visible in a single sitting.

    `games=0` means "until the human stops it": a finished game is followed by a fresh one
    with the next seed, forever. Nothing here ends on its own — the loop exits on Ctrl-C or
    when the browser window is closed, and both still close the log and the browser.
    """
    modes = (mode,) if isinstance(mode, str) else tuple(mode)
    # Mirror the window into the panel only when there is no window to look at.
    if shots is None:
        shots = bool(headless)
    log = LogWriter(log_path)
    session = BrowserSession(headless=headless, cdp=cdp)
    await session.start()
    adapter = GameAdapter(session.tab)
    board = None
    url = None
    if dashboard:
        from ui.dashboard import Dashboard

        board = Dashboard(port=dashboard_port, state_path=STATE_PATH,
                          control_path=CONTROL_PATH, screenshot_path=SHOT_PATH)
        url = board.start()
        if open_dashboard:
            # The panel opens in the human's own browser, not as another tab of the window
            # driving the game: stealing focus there would hide the game and background the
            # very tab the experiment depends on.
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", url])
                else:
                    import webbrowser

                    webbrowser.open(url)
            except Exception as exc:
                print("  (could not open the dashboard: %s)" % exc, flush=True)
    print("modes=%s  browser=%s  dashboard=%s  games=%s"
          % ("+".join(modes), session.mode, url or "off",
             "until stopped" if games <= 0 else games),
          flush=True)
    outcomes = []
    played = 0
    try:
        game_id = 1
        current_seed = seed
        control = new_control_state()
        while games <= 0 or played < games:
            current_mode = modes[played % len(modes)]
            hook = InteractiveHook(adapter, current_mode, current_seed, speed=speed,
                                   echo=echo, control=control, panel=dashboard,
                                   screenshot_interval=shot_interval, shots=shots)
            try:
                outcome = await play_interactive(adapter, current_mode, current_seed,
                                                 game_id, max_steps, log, hook)
            except ResetRequested:
                print("\n  reset requested: starting a fresh game\n", flush=True)
                game_id += 1
                current_seed += 1
                continue
            except Exception as exc:
                if browser_gone(adapter):
                    print("\n  browser window closed: stopping", flush=True)
                    break
                raise
            played += 1
            outcomes.append(outcome)
            if len(outcomes) > keep:
                # An endless demo must not accumulate every game it has ever played.
                outcomes.pop(0)
            if on_outcome is not None:
                on_outcome(outcome, played)
            game_id += 1
            current_seed += 1
            if between_games and (games <= 0 or played < games):
                await asyncio.sleep(between_games)
    finally:
        log.close()
        if board is not None:
            board.stop()
        await session.close()
    return outcomes
