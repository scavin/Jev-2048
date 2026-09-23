"""Player registry: one lookup from `--mode` to a policy.

A mode name says both things the experiment varies: the model that decides, and the state
design it is shown. `laya-features` is laya given the harness's one-ply simulation;
`jev-features` is jev given exactly the same thing.
"""

import labpaths  # noqa: F401

import prompts
from players.baselines import GreedyPlayer, HeuristicPlayer, RandomPlayer
from players.jev_board import JevBoardPlayer
from players.jev_features import JevFeaturesPlayer
from players.jev_history import JevHistoryPlayer
from players.jev_state import JevStatePlayer
from players.jev_state_history import JevStateHistoryPlayer
from players.laya_board import LayaBoardPlayer
from players.laya_features import LayaFeaturesPlayer
from players.laya_history import LayaHistoryPlayer
from players.laya_state import LayaStatePlayer
from players.laya_state_history import LayaStateHistoryPlayer

MODELS = ("jev", "laya")

MODEL_PLAYERS = {
    "jev": (JevBoardPlayer, JevStatePlayer, JevHistoryPlayer, JevFeaturesPlayer,
            JevStateHistoryPlayer),
    "laya": (LayaBoardPlayer, LayaStatePlayer, LayaHistoryPlayer, LayaFeaturesPlayer,
             LayaStateHistoryPlayer),
}

PLAYERS = {
    "random": RandomPlayer,
    "greedy": GreedyPlayer,
    "heuristic": HeuristicPlayer,
}
for _model, _classes in MODEL_PLAYERS.items():
    for _class in _classes:
        PLAYERS["%s-%s" % (_model, _class.design)] = _class

MODES = tuple(PLAYERS)
BASELINE_MODES = ("random", "greedy", "heuristic")
JEV_MODES = tuple("%s-%s" % ("jev", design) for design in prompts.DESIGNS)
LAYA_MODES = tuple("%s-%s" % ("laya", design) for design in prompts.DESIGNS)
MODEL_MODES = JEV_MODES + LAYA_MODES


def build(mode, seed=0, **kwargs):
    if mode not in PLAYERS:
        raise SystemExit("unknown mode %r; choose from %s" % (mode, ", ".join(MODES)))
    return PLAYERS[mode](seed=seed, **kwargs)


def uses_jev(mode):
    """Kept for callers that only care whether a network call is involved."""
    return mode in JEV_MODES


def model_of(mode):
    for model in MODELS:
        if mode.startswith(model + "-"):
            return model
    return "none"
