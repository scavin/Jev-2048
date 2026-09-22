"""Mode 2 and mode 3 together: the explicit counters plus the history."""

import labpaths  # noqa: F401

from players.jev_player import JevPlayer


class JevStateHistoryPlayer(JevPlayer):
    mode = "jev-state-history"
