"""Mode 3: the board plus what happened before it."""

import labpaths  # noqa: F401

from players.jev_player import JevPlayer


class JevHistoryPlayer(JevPlayer):
    mode = "jev-history"
