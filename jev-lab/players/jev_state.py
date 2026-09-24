"""Mode 2: the board plus the state the harness already tracks."""

import labpaths  # noqa: F401

from players.jev_player import JevPlayer


class JevStatePlayer(JevPlayer):
    mode = "jev-state"
