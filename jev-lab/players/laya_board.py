"""Mode 1: the board and nothing else."""

import labpaths  # noqa: F401

from players.laya_player import LayaPlayer


class LayaBoardPlayer(LayaPlayer):
    design = "board"
