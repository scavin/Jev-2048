"""Mode 2: the board plus the state the harness already tracks."""

import labpaths  # noqa: F401

from players.laya_player import LayaPlayer


class LayaStatePlayer(LayaPlayer):
    design = "state"
