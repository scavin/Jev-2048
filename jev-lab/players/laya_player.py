"""laya: a local typed-choice model, reached over the socket the repo already runs."""

import labpaths  # noqa: F401

from laya.client import LayaClient
from players.model_player import ModelPlayer


class LayaPlayer(ModelPlayer):
    model = "laya"

    def __init__(self, seed=0, client=None, host=None, port=None, attempts=2):
        self.host = host
        self.port = port
        super().__init__(seed=seed, client=client, attempts=attempts)

    def make_client(self, attempts=4):
        return LayaClient(host=self.host, port=self.port, attempts=attempts)
