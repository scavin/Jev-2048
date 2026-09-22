"""Player registry: one lookup from `--mode` to a policy."""

import labpaths  # noqa: F401

from players.baselines import GreedyPlayer, HeuristicPlayer, RandomPlayer
from players.jev_board import JevBoardPlayer
from players.jev_features import JevFeaturesPlayer
from players.jev_history import JevHistoryPlayer
from players.jev_state import JevStatePlayer
from players.jev_state_history import JevStateHistoryPlayer

PLAYERS = {
    "random": RandomPlayer,
    "greedy": GreedyPlayer,
    "heuristic": HeuristicPlayer,
    "jev-board": JevBoardPlayer,
    "jev-state": JevStatePlayer,
    "jev-history": JevHistoryPlayer,
    "jev-features": JevFeaturesPlayer,
    "jev-state-history": JevStateHistoryPlayer,
}

MODES = tuple(PLAYERS)
JEV_MODES = ("jev-board", "jev-state", "jev-history", "jev-features",
             "jev-state-history")


def build(mode, seed=0, **kwargs):
    if mode not in PLAYERS:
        raise SystemExit("unknown mode %r; choose from %s" % (mode, ", ".join(MODES)))
    return PLAYERS[mode](seed=seed, **kwargs)


def uses_jev(mode):
    return PLAYERS[mode].uses_jev
