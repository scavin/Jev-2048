"""The three non-jev control policies.

They exist to answer three separate questions about the jev modes: better than chance,
better than one-ply score greed, and how far from a hand-written evaluation. All three
only ever pick a legal direction, so their invalid-move rate is zero by construction —
which is itself the comparison for modes where jev is offered illegal moves.
"""

import random

import labpaths  # noqa: F401

from analysis import features
from game import simulator
from players.base import Decision, Player

# nneonneo's published weights for empty cells / monotonicity / smoothness, plus three
# additions (corner, merge potential, mobility). None of them were tuned on this benchmark.
WEIGHTS = {
    "empty_cells": 2.7,
    "monotonicity": 1.0,
    "smoothness": 0.1,
    "corner": 1.0,
    "merge": 0.6,
    "mobility": 1.0,
}


def evaluation(board):
    """Deterministic score for one board, in the units of the weights above."""
    largest = features.max_tile(board)
    corner = 1.0 if features.max_tile_in_corner(board) else 0.0
    return (
        WEIGHTS["empty_cells"] * features.empty_cells(board)
        + WEIGHTS["monotonicity"] * 4.0 * features.monotonicity(board)
        + WEIGHTS["smoothness"] * features.smoothness(board)
        + WEIGHTS["corner"] * (largest.bit_length() - 1) * corner
        + WEIGHTS["merge"] * features.merge_potential(board)
        + WEIGHTS["mobility"] * features.mobility(board)
    )


class RandomPlayer(Player):
    """Uniform over the legal directions, from its own seeded generator."""

    name = "random"

    def __init__(self, seed=0):
        super().__init__(seed)
        self.rng = random.Random(seed)

    async def choose(self, ctx):
        name = self.rng.choice(ctx.legal)
        return Decision(name=name, source=self.name, latency_ms=0.0,
                        detail={"legal": list(ctx.legal)})


class GreedyPlayer(Player):
    """Largest immediate score gain; ties go to the board with more space, then order."""

    name = "greedy"

    async def choose(self, ctx):
        ranked = []
        for name in ctx.legal:
            simulation = simulator.simulate(ctx.board, name)
            ranked.append((simulation.score_gain,
                           features.empty_cells(simulation.board), name))
        best = max(ranked)
        return Decision(name=best[2], source=self.name, latency_ms=0.0,
                        detail={"ranked": [{"direction": n, "score_gain": g, "empty_after": e}
                                           for g, e, n in ranked]})


class HeuristicPlayer(Player):
    """Argmax of a hand-written evaluation of the board one move ahead."""

    name = "heuristic"

    async def choose(self, ctx):
        ranked = []
        for name in ctx.legal:
            simulation = simulator.simulate(ctx.board, name)
            ranked.append((evaluation(simulation.board), name))
        best = max(ranked)
        return Decision(name=best[1], source=self.name, latency_ms=0.0,
                        detail={"evaluations": [{"direction": n, "value": round(v, 4)}
                                                for v, n in ranked],
                                "weights": WEIGHTS})


PLAYERS = {"random": RandomPlayer, "greedy": GreedyPlayer, "heuristic": HeuristicPlayer}
