"""One game of 2048, driven by one policy, recorded move by move.

The direction comes from `player.choose`. A hook may supply one instead, which is how the
interactive demo lets a human take a move from the dashboard; the loop cannot tell the two
apart, so a human move is recorded and measured exactly like a policy's. Everything else
here is harness work — read the page, build the state the mode asks for, hand the move to
the browser, measure what happened, tag the failures, write the line.
"""

import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass, field

import labpaths  # noqa: F401

from analysis import features as feat
from analysis.failure_detector import FailureDetector
from game import simulator
from jev.client import JevError
from players.base import DecisionContext

PROMPT_PREVIEW_CHARS = 2400
REACHED = (256, 512, 1024, 2048, 4096)


class Hook:
    """Runner callbacks. The default does nothing, so batch runs pay nothing."""

    async def before_step(self, live):
        return None

    async def choose(self, ctx):
        """A direction from the caller instead of the policy. None means "no opinion"."""
        return None

    async def after_step(self, live):
        return None

    async def on_end(self, live, outcome):
        return None


class LogWriter:
    """Append-only JSONL, one line per executed move, flushed as it is written."""

    def __init__(self, path):
        self.path = path
        self.handle = open(path, "a", buffering=1) if path else None

    def write(self, record):
        if self.handle:
            self.handle.write(json.dumps(record, default=str) + "\n")

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None


@dataclass
class GameOutcome:
    game_id: int
    seed: int
    mode: str
    score: int
    steps: int
    max_tile: int
    reached: dict
    ended: str
    abort_reason: str | None = None
    tag_counts: dict = field(default_factory=dict)
    invalid_moves: int = 0
    latencies: list = field(default_factory=list)
    wall_ms: list = field(default_factory=list)
    jev_calls: int = 0
    jev_rejections: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    kept_playing: bool = False
    wall_clock_ms: float = 0.0

    def to_dict(self):
        payload = dict(self.__dict__)
        latencies = sorted(self.latencies)
        payload["latency_avg"] = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
        payload["latency_p50"] = _percentile(latencies, 0.5)
        payload["latency_p95"] = _percentile(latencies, 0.95)
        return payload


def _percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = fraction * (len(ordered) - 1)
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 1)


class GameRunner:
    def __init__(self, adapter, player, mode, game_id, seed, max_steps=5000,
                 hook=None, log=None, detector=None, stats=None):
        self.adapter = adapter
        self.player = player
        self.mode = mode
        self.game_id = game_id
        self.seed = seed
        self.max_steps = max_steps
        self.hook = hook or Hook()
        self.log = log
        self.detector = detector or FailureDetector()
        # Cumulative counters, kept current after every step so a game cancelled from the
        # outside can still be reported for what it actually did rather than as zero.
        self.stats = stats if stats is not None else {}
        self.live = {
            "mode": mode, "game_id": game_id, "seed": seed, "step": 0,
            "status": "starting", "board": [], "score": 0, "max_tile": 0,
            "empty_cells": 0, "latency_ms": 0.0, "chosen": None, "probabilities": None,
            "recent_moves": [], "checks": {}, "features": {}, "failure_tags": [],
            "log_path": getattr(log, "path", None),
        }

    def _digest(self, observation):
        return {"board_hash": observation.board_hash, "score": observation.score,
                "max_tile": observation.max_tile, "empty_cells": observation.empty_cells}

    async def play(self):
        started = time.perf_counter()
        observation = self.adapter.current or await self.adapter.observe()
        actions = []
        invalid = []
        digests = []
        seen = Counter()
        latencies = []
        wall = []
        kept_playing = False
        ended = "max_steps"
        abort_reason = None
        jev_calls = 0
        jev_rejections = 0
        tokens_in = 0
        tokens_out = 0

        while True:
            if observation.over or observation.dead:
                ended = "game_over"
                break
            if self.max_steps > 0 and len(actions) >= self.max_steps:
                ended = "max_steps"
                break

            step = len(actions) + 1
            board = observation.rows()
            legal = simulator.legal_moves(board)
            if not legal:
                ended = "game_over"
                break
            used_features = {}
            if self.mode == "jev-features":
                used_features = feat.features_all(board)

            key = observation.symmetry_key
            ctx = DecisionContext(
                mode=self.mode, board=board, score=observation.score, step=step,
                legal=legal, last_move=actions[-1] if actions else None,
                recent_moves=list(actions), recent_actions=list(actions),
                recent_boards=list(digests), recent_invalid=list(invalid),
                pattern_repeats=seen[key], features=used_features,
                failure_flags=dict(self.live.get("checks", {})),
            )

            # Only the position is refreshed here. The last decision stays on screen while
            # the loop is paused, so a human can read why that move was chosen before
            # releasing the next one.
            self.live.update(status="deciding", step=step, board=board,
                             score=observation.score, max_tile=observation.max_tile,
                             empty_cells=observation.empty_cells,
                             recent_moves=list(actions[-16:]),
                             features={name: f.as_dict() for name, f in used_features.items()})
            await self.hook.before_step(self.live)

            try:
                decision = await self.hook.choose(ctx)
                if decision is None:
                    decision = await self.player.choose(ctx)
            except JevError as exc:
                ended = "aborted"
                abort_reason = str(exc)
                break

            simulation = simulator.simulate(board, decision.name)
            after, page_info = await self.adapter.apply(decision.name, observation)
            score_gain = after.score - observation.score

            record = {
                "game_id": self.game_id,
                "seed": self.seed,
                "mode": self.mode,
                "step": step,
                "board_before": board,
                "board_after": after.rows(),
                "action": decision.name,
                "action_valid": simulation.valid,
                "score_before": observation.score,
                "score_after": after.score,
                "score_gain": score_gain,
                "score_gain_expected": simulation.score_gain,
                "max_tile": observation.max_tile,
                "empty_cells": observation.empty_cells,
                "empty_cells_after": after.empty_cells,
                "latency_ms": round(decision.latency_ms, 1),
                "step_wall_ms": page_info["wall_ms"],
                "recent_moves": list(actions[-16:]),
                "board_hash": observation.board_hash,
                "state_hash": observation.state_hash,
                "board_hash_after": after.board_hash,
                "largest_corner": feat.largest_corner(board),
                "largest_corner_after": feat.largest_corner(after.board),
                "monotonicity": round(feat.monotonicity(board), 3),
                "monotonicity_after": round(feat.monotonicity(after.board), 3),
                "page_reacted": page_info["page_reacted"],
                "read_ms": round(after.read_ms, 1),
                "decision_source": decision.source,
                "jev_probabilities": decision.probabilities,
                "jev_confidence": decision.confidence,
                "jev_attempts": decision.attempts,
                "jev_model": decision.model,
                "jev_usage": decision.usage,
                "prompt_preview": decision.prompt_text[:PROMPT_PREVIEW_CHARS],
                "request_state": decision.request_state,
                "decision_detail": decision.detail,
                "features_after": {name: f.as_dict() for name, f in used_features.items()},
                "failure_tags": [],
                "ts": round(time.time(), 3),
            }

            detection = self.detector.observe(record)
            record["failure_tags"] = detection.tags
            if self.log:
                self.log.write(record)

            actions.append(decision.name)
            if not simulation.valid:
                invalid.append(decision.name)
            digests.append(self._digest(observation))
            seen[key] += 1
            latencies.append(decision.latency_ms)
            wall.append(page_info["wall_ms"])
            usage = decision.usage or {}
            # A human move in a jev mode costs no request, so it is not counted as one.
            if self.player.uses_jev and decision.source != "human":
                jev_calls += 1
            jev_rejections += max(0, decision.attempts - 1)
            tokens_in += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            tokens_out += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

            self.live.update(
                status="moving", step=step, board=after.rows(), score=after.score,
                max_tile=after.max_tile, empty_cells=after.empty_cells,
                latency_ms=round(decision.latency_ms, 1), chosen=decision.name,
                probabilities=decision.probabilities,
                recent_moves=list(actions[-16:]), checks=detection.checks,
                failure_tags=detection.tags, message=after.message,
            )
            self.stats.update(
                score=after.score, steps=len(actions), max_tile=after.max_tile,
                tag_counts=dict(self.detector.tally), invalid_moves=len(invalid),
                latencies=list(latencies), wall_ms=list(wall), jev_calls=jev_calls,
                jev_rejections=jev_rejections, tokens_in=tokens_in, tokens_out=tokens_out,
                kept_playing=kept_playing,
            )
            await self.hook.after_step(self.live)

            observation = after
            if after.won:
                observation = await self.adapter.keep_playing()
                kept_playing = True
            if observation.over or observation.dead:
                ended = "game_over"
                break

        outcome = GameOutcome(
            game_id=self.game_id, seed=self.seed, mode=self.mode,
            score=observation.score, steps=len(actions),
            max_tile=observation.max_tile,
            reached={str(tile): observation.max_tile >= tile for tile in REACHED},
            ended=ended, abort_reason=abort_reason,
            tag_counts=dict(self.detector.tally), invalid_moves=len(invalid),
            latencies=latencies, wall_ms=wall, jev_calls=jev_calls,
            jev_rejections=jev_rejections, tokens_in=tokens_in, tokens_out=tokens_out,
            kept_playing=kept_playing,
            wall_clock_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        self.live.update(status=ended, board=observation.rows(), score=observation.score,
                         max_tile=observation.max_tile, empty_cells=observation.empty_cells,
                         message=observation.message)
        await self.hook.on_end(self.live, outcome)
        return outcome


async def play_one(adapter, player, mode, game_id, seed, max_steps=5000, log=None,
                   hook=None, stats=None):
    """Open a seeded game and play it to the end."""
    await adapter.open(seed)
    runner = GameRunner(adapter, player, mode, game_id, seed, max_steps=max_steps,
                        log=log, hook=hook, stats=stats)
    return await runner.play()


async def gather_limited(coros, limit):
    """Run coroutines with a fixed concurrency, keeping results in submission order."""
    if limit <= 1:
        return [await coro for coro in coros]
    semaphore = asyncio.Semaphore(limit)

    async def guarded(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(guarded(coro) for coro in coros))
