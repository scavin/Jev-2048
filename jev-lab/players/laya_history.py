"""Mode 3: the board plus what happened before it."""

import labpaths  # noqa: F401

from players.laya_player import LayaPlayer


class LayaHistoryPlayer(LayaPlayer):
    design = "history"
