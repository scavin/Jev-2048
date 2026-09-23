"""Mode 2 and mode 3 together: the explicit counters plus the history."""

import labpaths  # noqa: F401

from players.laya_player import LayaPlayer


class LayaStateHistoryPlayer(LayaPlayer):
    design = "state-history"
