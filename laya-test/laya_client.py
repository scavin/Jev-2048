"""Thin client for the persistent Laya decision server.

Usage from the harness:

    laya = LayaClient()
    result = laya.ask(state, {"q1": {...}})          # one round trip, many questions
    result = laya.ask_many([(state_a, qs_a), ...])   # batched over separate states
"""

import json
import socket

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8791


class LayaError(RuntimeError):
    pass


class LayaClient:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=600.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None
        self._reader = None
        self._counter = 0

    def _connect(self):
        if self._sock is None:
            self._sock = socket.create_connection((self.host, self.port), timeout=30.0)
            self._sock.settimeout(self.timeout)
            self._reader = self._sock.makefile("rb")
        return self._sock

    def close(self):
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _round_trip(self, payload):
        self._connect()
        self._counter += 1
        payload = dict(payload, id=self._counter)
        self._sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        line = self._reader.readline()
        if not line:
            self.close()
            raise LayaError("laya server closed the connection")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise LayaError(reply.get("error") or "unknown laya failure")
        return reply["result"]

    def ask(self, state, questions):
        """One state, many questions -> answers dict."""
        return self._round_trip({"state": state, "questions": questions})

    def ask_many(self, cases):
        """cases: iterable of (state, questions). One round trip per case."""
        return [self.ask(state, questions) for state, questions in cases]

    def ping(self):
        return self._round_trip({"op": "ping"})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
