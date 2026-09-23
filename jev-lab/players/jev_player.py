"""jev: a remote typed-choice model, reached over the network."""

import labpaths  # noqa: F401

from jev.client import JevClient
from players.model_player import ModelPlayer


class JevPlayer(ModelPlayer):
    model = "jev"

    def __init__(self, seed=0, client=None, model=None, attempts=4):
        self.model_name = model
        super().__init__(seed=seed, client=client, attempts=attempts)

    def make_client(self, attempts=4):
        return JevClient(model=self.model_name, attempts=attempts)
