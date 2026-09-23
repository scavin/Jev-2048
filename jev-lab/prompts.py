"""What the harness shows the model, per state design.

The experiment has exactly one variable: the state handed over. So the goal, the rules and
the four candidate labels are byte-identical in every design, and only `state` and
`criteria` change:

| design        | added to the board                                     |
|---------------|--------------------------------------------------------|
| `board`       | nothing                                                |
| `state`       | score, max tile, empties, last move, recent moves, step, invalid attempts |
| `history`     | the last 16 actions, recent board digests, pattern repeat count, invalid attempts |
| `features`    | the harness's own one-ply simulation of all four directions |

Nothing else is ever added. No heuristics, no advice, no plan.
"""

from dataclasses import dataclass, field

import labpaths  # noqa: F401

DESIGNS = ("board", "state", "history", "features", "state-history")
PRESENT_ORDER = ("up", "down", "left", "right")

GOAL = "Avoid game over and reach the highest tile possible."

RULES = (
    "2048 rules: a move slides every tile toward that edge. Two tiles of equal value that "
    "collide merge into one tile of their sum, and the score increases by that sum. After a "
    "move that changes the board, one new tile of value 2 or 4 appears in an empty cell. "
    "The game is over when no direction changes the board."
)

DIRECTION_TEXT = {
    "up": "Slide every tile toward the top edge.",
    "down": "Slide every tile toward the bottom edge.",
    "left": "Slide every tile toward the left edge.",
    "right": "Slide every tile toward the right edge.",
}


@dataclass
class Context:
    """Everything the harness knows at decision time. Each design reads a slice of it."""

    design: str
    board: list
    score: int
    step: int
    max_tile: int
    empty_cells: int
    last_move: str | None = None
    recent_moves: list = field(default_factory=list)
    recent_actions: list = field(default_factory=list)
    recent_boards: list = field(default_factory=list)
    recent_invalid: list = field(default_factory=list)
    pattern_repeats: int = 0
    features: dict = field(default_factory=dict)
    failure_flags: dict = field(default_factory=dict)


@dataclass
class Prompt:
    state: dict
    criteria: dict
    instructions: dict
    text: str

    def body(self, model):
        return {
            "model": model,
            "state": self.state,
            "questions": {
                "direction": {
                    "type": "choice",
                    "criteria": self.criteria,
                    "instructions": self.instructions,
                }
            },
        }


def instructions():
    """Identical in every design: the goal and the rules are not the experimental variable."""
    return {"goal": GOAL, "rules": RULES}


def _criteria(ctx):
    if ctx.design == "features":
        return {
            name: {"description": DIRECTION_TEXT[name], **ctx.features[name].as_dict()}
            for name in PRESENT_ORDER
        }
    return {name: {"description": DIRECTION_TEXT[name]} for name in PRESENT_ORDER}


def build(ctx):
    """Assemble the request body and the readable rendering of it."""
    builders = {
        "board": _state_board_only,
        "state": _state_explicit,
        "history": _state_history,
        "features": _state_features,
        "state-history": _state_explicit_and_history,
    }
    if ctx.design not in builders:
        raise ValueError("unknown state design %r" % (ctx.design,))
    state = builders[ctx.design](ctx)
    criteria = _criteria(ctx)
    text = render(ctx.design, state, criteria)
    return Prompt(state=state, criteria=criteria, instructions=instructions(), text=text)


# ------------------------------------------------------------------ state builders

def _state_board_only(ctx):
    return {"board": ctx.board}


def _state_explicit(ctx):
    """Board plus the state the harness already tracks for free."""
    invalid = {}
    for name in ctx.recent_invalid:
        invalid[name] = invalid.get(name, 0) + 1
    return {
        "board": ctx.board,
        "score": ctx.score,
        "max_tile": ctx.max_tile,
        "empty_cells": ctx.empty_cells,
        "last_move": ctx.last_move,
        "recent_moves": list(ctx.recent_moves[-5:]),
        "step": ctx.step,
        "recent_invalid_moves": [{"direction": name, "count": count}
                                 for name, count in sorted(invalid.items())],
        "repeated_move_pattern": _alternating(ctx.recent_moves),
    }


def _state_history(ctx):
    """Board plus what happened before it. Facts only — no advice about them."""
    invalid = {}
    for name in ctx.recent_invalid:
        invalid[name] = invalid.get(name, 0) + 1
    return {
        "board": ctx.board,
        "recent_actions": list(ctx.recent_actions[-16:]),
        "recent_board_states": list(ctx.recent_boards[-8:]),
        "current_board_seen_before": ctx.pattern_repeats,
        "recent_action_pattern": _pattern(ctx.recent_actions[-6:]),
        "recent_invalid_attempts": [{"direction": name, "count": count}
                                    for name, count in sorted(invalid.items())],
        "step": ctx.step,
    }


def _state_features(ctx):
    """The board, and the harness's own one-ply simulation in the criteria."""
    return {
        "board": ctx.board,
        "score": ctx.score,
        "step": ctx.step,
    }


def _state_explicit_and_history(ctx):
    """Mode 2 and mode 3 together.

    Mode 3 as specified replaces mode 2's counters with history rather than adding to them,
    so comparing the two measures two changes at once. This condition holds the counters
    fixed and adds history on top, which is what isolates the effect of the history itself.
    """
    state = _state_explicit(ctx)
    state.update({
        "recent_actions": list(ctx.recent_actions[-16:]),
        "recent_board_states": list(ctx.recent_boards[-8:]),
        "current_board_seen_before": ctx.pattern_repeats,
        "recent_action_pattern": _pattern(ctx.recent_actions[-6:]),
    })
    return state


# ------------------------------------------------------------------ small facts

def _alternating(moves, run=4):
    """True when the tail of the move list is a two-move alternation repeated `run` times."""
    if len(moves) < run:
        return False
    tail = moves[-run:]
    return all(tail[i] != tail[i - 1] for i in range(1, run)) and \
        all(tail[i] == tail[i - 2] for i in range(2, run))


def _pattern(moves):
    return ", ".join(name.upper() for name in moves)


# ------------------------------------------------------------------ rendering

def _board_text(board):
    return "\n".join(" ".join(str(v) for v in row) for row in board)


def _render_state(state):
    lines = ["Board:", _board_text(state["board"]), "",
             "Score: %d" % state["score"],
             "Max tile: %d" % state["max_tile"],
             "Empty cells: %d" % state["empty_cells"],
             "Last move: %s" % (state["last_move"] or "none").upper(),
             "Recent moves:",
             _pattern(state["recent_moves"]) or "none",
             "Step: %d" % state["step"]]
    if state["recent_invalid_moves"]:
        lines.append("Recent invalid moves: " + ", ".join(
            "%s x%d" % (item["direction"].upper(), item["count"])
            for item in state["recent_invalid_moves"]))
    lines.append("Repeated move pattern: %s"
                 % ("yes" if state["repeated_move_pattern"] else "no"))
    lines.append("")
    return lines


def _render_history(state):
    lines = ["Recent actions:",
             _pattern(state["recent_actions"]) or "none", "",
             "Recent board states:"]
    for index, digest in enumerate(state["recent_board_states"], start=1):
        lines.append("  %d. hash=%s score=%d max=%d empty=%d"
                     % (index, digest["board_hash"], digest["score"],
                        digest["max_tile"], digest["empty_cells"]))
    lines += ["",
              "Current board pattern seen before: %d times" % state["current_board_seen_before"],
              "Recent action pattern: %s" % (state["recent_action_pattern"] or "none")]
    for item in state.get("recent_invalid_attempts", []):
        lines.append("Invalid %s attempts recently: %d"
                     % (item["direction"].upper(), item["count"]))
    lines.append("")
    return lines


def _render_features(state, criteria):
    lines = ["Board:", _board_text(state["board"]), "",
             "Score: %d" % state["score"], "Step: %d" % state["step"], ""]
    for name in PRESENT_ORDER:
        block = criteria[name]
        lines.append("%s:" % name.upper())
        for key in ("valid", "score_gain", "merge_count", "empty_cells_after",
                    "max_tile_after", "max_tile_in_corner", "corner_preserved",
                    "monotonicity", "smoothness", "changed_cells", "mobility",
                    "board_entropy"):
            lines.append("  %s: %s" % (key, str(block[key]).lower()
                                       if isinstance(block[key], bool) else block[key]))
        lines.append("")
    return lines


def render(design, state, criteria):
    """The prompt as text, for the log and the dashboard. Not sent to the model — `state` is."""
    if design == "board":
        lines = ["Current 2048 board:", "", _board_text(state["board"]), ""]
    elif design == "state":
        lines = _render_state(state)
    elif design == "history":
        lines = ["Board:", _board_text(state["board"]), ""] + _render_history(state)
    elif design == "state-history":
        lines = _render_state(state) + _render_history(state)
    else:
        lines = _render_features(state, criteria)

    lines += ["Choose one move:", ""]
    lines += [name.upper() for name in PRESENT_ORDER]
    lines += ["", "Goal:", GOAL]
    return "\n".join(lines)
