"""TypeSafe's jev as a 2048 player.

Reuses jev-ultrafast's own model client (`post_json` + `validate_choice`) so the network
path is the shipped one. Only the question set differs: instead of choosing a browser
operation over observed elements, jev chooses a direction over the legal moves.

jev consumes structured state, never screenshots, so the board is handed over as JSON.
"""

import os
import sys
import time

JEV_REPO = os.environ.get("JEV_REPO", "/Users/scavin/Documents/Github/Jev")
if JEV_REPO not in sys.path:
    sys.path.insert(0, JEV_REPO)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"

DIRECTIONS = ("up", "right", "down", "left")
DIRECTION_INDEX = {name: index for index, name in enumerate(DIRECTIONS)}

# The rules of the game, stated once. No tactical advice: this is the neutral condition.
RULES = (
    "2048 rules: a move slides every tile toward that edge. Two tiles of equal value that "
    "collide merge into one tile of their sum, and the score increases by that sum. After a "
    "move that changes the board, one new tile of value 2 or 4 appears in an empty cell. "
    "The game is over when no direction changes the board."
)
GOAL = "Play 2048 and maximise the final score."

# The hinted condition adds tactics on top of the same rules.
HINT = (
    " Keep the largest tile in a corner and keep empty cells available. Prefer moves that "
    "merge tiles over moves that only shift them."
)

CRITERIA = {
    "up": "Slide every tile toward the top edge.",
    "right": "Slide every tile toward the right edge.",
    "down": "Slide every tile toward the bottom edge.",
    "left": "Slide every tile toward the left edge.",
}


def load_env(path=None):
    """Read KEY=VALUE lines from the jev .env without clobbering the real environment."""
    path = path or os.path.join(JEV_REPO, ".env")
    if not os.path.exists(path):
        return
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_model_module():
    """Import jev's own `model.py` without running the package `__init__`.

    `jev_ultrafast/__init__.py` imports the full browser agent, which drags in
    `browser_harness`. Choosing a direction never touches the browser, so the package is
    registered under a private name whose `__path__` points at the real directory; the
    relative `from .questions import ...` inside model.py then resolves normally.
    """
    import importlib.util
    import types

    package = "jev_model_standalone"
    if package + ".model" in sys.modules:
        return sys.modules[package + ".model"]

    module = types.ModuleType(package)
    module.__path__ = [os.path.join(JEV_REPO, "jev_ultrafast")]
    sys.modules[package] = module

    path = os.path.join(JEV_REPO, "jev_ultrafast", "model.py")
    spec = importlib.util.spec_from_file_location(package + ".model", path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[package + ".model"] = loaded
    spec.loader.exec_module(loaded)
    return loaded


class JevError(RuntimeError):
    pass


class JevClient:
    """One TypeSafe request per direction choice."""

    def __init__(self, prompt="neutral", model=None, history_size=4):
        load_env()
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise JevError("TYPESAFE_API_KEY missing (see %s/.env)" % JEV_REPO)
        module = load_model_module()
        self._post_json = module.post_json
        self._validate_choice = module.validate_choice
        self.model = model or os.environ.get("TYPESAFE_MODEL", "jev-latest")
        self.prompt = prompt
        self.history_size = history_size
        self.calls = 0
        self.rejected = 0

    def instructions(self):
        rules = RULES + (HINT if self.prompt == "hinted" else "")
        return {"goal": GOAL, "rules": rules}

    def build_body(self, board, score, largest, legal, recent):
        criteria = {name: CRITERIA[name] for name in legal}
        return {
            "model": self.model,
            "state": {
                "board": board,
                "score": score,
                "largest_tile": largest,
                "empty_cells": sum(row.count(0) for row in board),
                "legal_moves": list(legal),
                "recent_moves": list(recent)[-self.history_size:],
            },
            "questions": {
                "direction": {
                    "type": "choice",
                    "criteria": criteria,
                    "instructions": self.instructions(),
                }
            },
        }

    def choose(self, board, score, largest, legal, recent=(), attempts=4):
        """Return the chosen direction name plus the raw decision metadata.

        A single malformed response must not end a game. jev's own `validate_choice` is
        strict — exact key set, probabilities summing to 1, and the choice as argmax — so a
        flaky answer is re-asked a bounded number of times. The count of rejected answers is
        reported because it is itself a reliability measurement of the model.
        """
        body = self.build_body(board, score, largest, legal, recent)
        criteria = body["questions"]["direction"]["criteria"]
        total_ms = 0
        last_rejection = None

        for attempt in range(attempts):
            started = time.perf_counter()
            result = self._post_json(ENDPOINT, os.environ["TYPESAFE_API_KEY"], body)
            total_ms += round((time.perf_counter() - started) * 1000)
            self.calls += 1

            answer = result.get("answers", {}).get("direction", {})
            try:
                validated = self._validate_choice(answer, criteria)
            except ValueError as exc:
                self.rejected += 1
                last_rejection = {"error": str(exc), "raw_answer": answer}
                if attempt + 1 < attempts:
                    time.sleep(0.3 * (attempt + 1))
                continue

            name = validated["choice"]
            return {
                "name": name,
                "direction": DIRECTION_INDEX[name],
                "confidence": validated.get("confidence"),
                "probabilities": validated.get("probabilities"),
                "latency_ms": total_ms,
                "attempts": attempt + 1,
                "model": result.get("model"),
                "usage": result.get("usage", {}),
            }

        raise JevError("%d consecutive invalid TypeSafe responses; last: %r"
                       % (attempts, last_rejection))
