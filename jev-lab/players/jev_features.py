"""Mode 4: the board plus the harness's own one-ply simulation of all four directions."""

import labpaths  # noqa: F401

from players.jev_player import JevPlayer


class JevFeaturesPlayer(JevPlayer):
    mode = "jev-features"
