"""Deterministic board measurements.

Two kinds live here:

* board-level facts (`empty_cells`, `monotonicity`, ...) — what a position looks like;
* one-step features (`features_for`) — what each direction does to it, which is the
  deterministic work mode 4 hands to jev.

Everything is computed from a board alone. No randomness is modelled: the tile the page
will spawn is unknown at decision time and is deliberately not guessed.
"""

import math
from dataclasses import dataclass

import labpaths  # noqa: F401

from game import simulator
from game.state import CORNERS

SIZE = 4


def _logs(board):
    """log2 of every tile, 0 for an empty cell."""
    return [[0.0 if v == 0 else math.log2(v) for v in row] for row in board]


def empty_cells(board):
    return sum(1 for row in board for v in row if v == 0)


def max_tile(board):
    return max((v for row in board for v in row), default=0)


def largest_corner(board):
    """Which corner holds the largest tile, or None.

    Only a *unique* largest tile has a corner worth talking about: early on the board holds
    several 2s and 4s, and calling one of them "the big tile" would invent a corner
    strategy the player has not started. A tie therefore reports None.
    """
    values = [v for row in board for v in row if v]
    if not values:
        return None
    largest = max(values)
    if values.count(largest) != 1:
        return None
    for name, (r, c) in CORNERS.items():
        if board[r][c] == largest:
            return name
    return None


def max_tile_in_corner(board):
    """Whether the largest tile — when it is unique — sits in a corner."""
    return largest_corner(board) is not None


def monotonicity(board):
    """How consistently rows and columns run one way, in [0, 1].

    Each line's four possible monotone directions are scored by the total drop they
    explain; the best is kept and divided by the line's total variation. 1.0 means every
    row and column is monotone, which is the shape a large tile wants.
    """
    logs = _logs(board)
    lines = [row for row in logs] + [[logs[r][c] for r in range(SIZE)] for c in range(SIZE)]
    total = 0.0
    for line in lines:
        values = [v for v in line if v > 0]
        if len(values) < 2:
            total += 1.0
            continue
        best = 0.0
        for sequence in (values, values[::-1]):
            explained = sum(max(0.0, sequence[i] - sequence[i + 1])
                            for i in range(len(sequence) - 1))
            best = max(best, explained)
        variation = sum(abs(values[i] - values[i + 1]) for i in range(len(values) - 1))
        total += 1.0 if variation == 0 else best / variation
    return total / len(lines)


def smoothness(board):
    """Negative total log2 gap between adjacent tiles; 0.0 is perfectly smooth.

    Only neighbouring non-empty pairs count: an empty neighbour is free space, not a gap.
    """
    logs = _logs(board)
    penalty = 0.0
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c] == 0:
                continue
            if c + 1 < SIZE and board[r][c + 1]:
                penalty += abs(logs[r][c] - logs[r][c + 1])
            if r + 1 < SIZE and board[r + 1][c]:
                penalty += abs(logs[r][c] - logs[r + 1][c])
    return -penalty


def mobility(board):
    """How many directions still change the board."""
    return len(simulator.legal_moves(board))


def board_entropy(board):
    """Shannon entropy in bits of the tile-value distribution (0 for an empty board)."""
    values = [v for row in board for v in row if v]
    if not values:
        return 0.0
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    total = len(values)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def merge_potential(board):
    """Adjacent equal pairs available before any move is made."""
    pairs = 0
    for r in range(SIZE):
        for c in range(SIZE):
            value = board[r][c]
            if not value:
                continue
            if c + 1 < SIZE and board[r][c + 1] == value:
                pairs += 1
            if r + 1 < SIZE and board[r + 1][c] == value:
                pairs += 1
    return pairs


@dataclass(frozen=True)
class DirectionFeatures:
    """One-step lookahead for a single direction. Exactly one ply, by construction."""

    direction: str
    valid: bool
    score_gain: int
    merge_count: int
    empty_cells_after: int
    max_tile_after: int
    max_tile_in_corner: bool
    corner_preserved: bool
    monotonicity: float
    smoothness: float
    changed_cells: int
    mobility: int
    board_entropy: float

    def as_dict(self):
        return {
            "valid": self.valid,
            "score_gain": self.score_gain,
            "merge_count": self.merge_count,
            "empty_cells_after": self.empty_cells_after,
            "max_tile_after": self.max_tile_after,
            "max_tile_in_corner": self.max_tile_in_corner,
            "corner_preserved": self.corner_preserved,
            "monotonicity": round(self.monotonicity, 3),
            "smoothness": round(self.smoothness, 3),
            "changed_cells": self.changed_cells,
            "mobility": self.mobility,
            "board_entropy": round(self.board_entropy, 3),
        }


def features_for(board, direction):
    """Everything one ply of that direction produces, measured on the slid board.

    The spawned tile is not modelled, so every number describes the position the player
    is certain about: the one that exists the instant the move lands.
    """
    simulation = simulator.simulate(board, direction)
    after = simulation.board
    corner = largest_corner(board)
    return DirectionFeatures(
        direction=direction,
        valid=simulation.valid,
        score_gain=simulation.score_gain,
        merge_count=simulation.merge_count,
        empty_cells_after=empty_cells(after),
        max_tile_after=max_tile(after),
        max_tile_in_corner=max_tile_in_corner(after),
        corner_preserved=corner is not None and largest_corner(after) == corner,
        monotonicity=monotonicity(after),
        smoothness=smoothness(after),
        changed_cells=simulation.changed_cells,
        mobility=mobility(after),
        board_entropy=board_entropy(after),
    )


def features_all(board):
    """One-step features for all four directions, keyed by direction name."""
    return {name: features_for(board, name) for name in simulator.DIRECTIONS}


def board_summary(board):
    """The board-level facts, cheap enough to compute on every step."""
    return {
        "max_tile": max_tile(board),
        "empty_cells": empty_cells(board),
        "monotonicity": round(monotonicity(board), 3),
        "smoothness": round(smoothness(board), 3),
        "mobility": mobility(board),
        "merge_potential": merge_potential(board),
        "board_entropy": round(board_entropy(board), 3),
        "largest_corner": largest_corner(board),
    }
