"""The player interface: a policy sees a decision context, returns one direction.

Every policy in the lab — three deterministic baselines and four jev modes — implements
this one method, so the runner cannot tell them apart and no policy gets a shortcut.
"""

from dataclasses import dataclass, field

import labpaths  # noqa: F401


@dataclass
class DecisionContext:
    """What a policy is allowed to look at, assembled once per step by the runner.

    `design` is the experiment's variable — which state the harness hands over. The model is
    the other axis and lives on the policy, not here.
    """

    design: str
    board: list
    score: int
    step: int
    legal: list
    last_move: str | None = None
    recent_moves: list = field(default_factory=list)
    recent_actions: list = field(default_factory=list)
    recent_boards: list = field(default_factory=list)
    recent_invalid: list = field(default_factory=list)
    pattern_repeats: int = 0
    features: dict = field(default_factory=dict)
    failure_flags: dict = field(default_factory=dict)

    @property
    def max_tile(self):
        return max((v for row in self.board for v in row), default=0)

    @property
    def empty_cells(self):
        return sum(1 for row in self.board for v in row if v == 0)


@dataclass
class Decision:
    """One choice, with whatever the policy can honestly report about it."""

    name: str
    source: str
    probabilities: dict | None = None
    confidence: float | None = None
    latency_ms: float = 0.0
    attempts: int = 1
    model: str | None = None
    usage: dict = field(default_factory=dict)
    prompt_text: str = ""
    request_state: dict | None = None
    features: dict | None = None
    detail: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "action": self.name,
            "decision_source": self.source,
            "jev_probabilities": self.probabilities,
            "jev_confidence": self.confidence,
            "latency_ms": round(self.latency_ms, 1),
            "jev_attempts": self.attempts,
            "jev_model": self.model,
            "jev_usage": self.usage,
            "prompt_preview": self.prompt_text,
            "request_state": self.request_state,
            "decision_detail": self.detail,
        }


class Player:
    """Base policy. `model` is "jev", "laya", or "none" for the deterministic baselines."""

    name = "player"
    model = "none"
    uses_jev = False

    def __init__(self, seed=0):
        self.seed = seed

    async def choose(self, ctx: DecisionContext) -> Decision:
        raise NotImplementedError
