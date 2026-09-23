"""Mode 4: the board plus the harness's own one-ply simulation of all four directions."""

import labpaths  # noqa: F401

from players.laya_player import LayaPlayer


class LayaFeaturesPlayer(LayaPlayer):
    design = "features"
