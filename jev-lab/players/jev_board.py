"""Mode 1: the board and nothing else."""

import labpaths  # noqa: F401

from players.jev_player import JevPlayer


class JevBoardPlayer(JevPlayer):
    mode = "jev-board"
