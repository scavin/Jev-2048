"""Deterministic 2048 rules, used for legality, one-step features and every baseline.

The rules come from `laya-test/reference2048.py`, an engine written from the rules rather
than copied out of the game, and already used as a differential oracle against the page.
Reusing it means "the harness thinks this move is legal" and "the page agrees" are two
independent statements.
"""

from dataclasses import dataclass

import labpaths  # noqa: F401

import reference2048 as ref

DIRECTION_INDEX = {"up": ref.UP, "right": ref.RIGHT, "down": ref.DOWN, "left": ref.LEFT}
INDEX_DIRECTION = {index: name for name, index in DIRECTION_INDEX.items()}
DIRECTIONS = ("up", "right", "down", "left")


@dataclass(frozen=True)
class Simulation:
    """The board a direction produces, before the page adds its random tile."""

    direction: str
    board: list
    score_gain: int
    valid: bool
    merge_count: int
    changed_cells: int


def simulate(board, direction):
    """Apply one direction with no randomness: the harness's own copy of the move."""
    index = DIRECTION_INDEX[direction]
    after, gained, moved = ref.move(board, index)
    before_tiles = sum(1 for row in board for v in row if v)
    after_tiles = sum(1 for row in after for v in row if v)
    changed = sum(1 for r in range(4) for c in range(4) if board[r][c] != after[r][c])
    return Simulation(
        direction=direction,
        board=after,
        score_gain=gained,
        valid=bool(moved),
        # A merge is the only thing that removes a tile without emptying a cell, so the
        # drop in tile count is exactly the merge count.
        merge_count=before_tiles - after_tiles,
        changed_cells=changed,
    )


def simulate_all(board):
    return {name: simulate(board, name) for name in DIRECTIONS}


def legal_moves(board):
    return [name for name in DIRECTIONS if simulate(board, name).valid]


def is_dead(board):
    return not ref.moves_available(board)


def max_tile(board):
    return max((v for row in board for v in row), default=0)


def empty_cells(board):
    return sum(1 for row in board for v in row if v == 0)
