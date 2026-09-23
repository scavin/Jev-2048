"""The laya decision layer: the same experiment, decided by a local model.

laya is a local checkpoint (ModernBERT-large on MPS) served by `laya-test/laya_server.py`, the
persistent process this repository already runs so a test loop does not pay a ~21 s load per
question. That server and its thin client are reused as-is, the same way the page client and
the rules engine are.

The contract is the one the lab already relies on: a `choice` question returns a `choice`, a
`probabilities` map over exactly the offered candidates, and a `confidence`. That is the same
shape jev returns, which is why the same state builders and the same reporting work for both
models. The check below is deliberately the same rule jev's shipped validator applies — key
set, probabilities in [0, 1] summing to 1, declared choice as argmax — so a rejection means
the same thing whichever model produced it. It is implemented here rather than imported so
that running the local model does not require the jev checkout.

`confidence` is recorded and never thresholded: `laya-test/CALIBRATION.md` measured it staying
near zero even on correct answers.
"""

import asyncio
import contextlib
import json
import math
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass, field

try:
    import fcntl
except ImportError:  # not POSIX; a thread lock is all that is available there
    fcntl = None

import labpaths  # noqa: F401

LAYA_TEST_DIR = os.path.join(labpaths.REPO, "laya-test")
if LAYA_TEST_DIR not in sys.path:
    sys.path.insert(0, LAYA_TEST_DIR)

from laya_client import LayaClient as _Transport, LayaError  # noqa: E402

# Where the local installation lives, per /Users/scavin/Documents/models/laya/AGENTS.md.
LAYA_HOME = os.environ.get("LAYA_HOME", "/Users/scavin/Documents/models/laya")
LAYA_SERVER = os.path.join(LAYA_TEST_DIR, "laya_server.py")

DEFAULT_HOST = os.environ.get("LAYA_HOST") or "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("LAYA_PORT") or 8791)
# The checkpoint loads once into the server; a question is then tens to a few hundred ms.
DEFAULT_TIMEOUT = 120.0


def start_hint(port=None):
    """The command that starts the server this client speaks to.

    The checkpoint lives in the local installation's venv, so the server has to be started
    with that interpreter rather than the one running the lab.
    """
    return "%s/.venv/bin/python %s --port %d" % (LAYA_HOME, LAYA_SERVER,
                                                 port or DEFAULT_PORT)


# The checkpoint is not thread-safe. Two overlapping calls race the Metal command buffer and
# take the whole server down: a 12-way burst killed it with
# `failed assertion _status < MTLCommandBufferStatusCommitted at line 323 in
# -[IOGPUMetalCommandBuffer setCurrentCommandEncoder:]`. Concurrency in the lab must
# therefore never become concurrency at the model.
GATE_PATH = os.path.join(labpaths.UI_DIR, ".laya-model.lock")
_THREAD_LOCK = threading.Lock()


@contextlib.contextmanager
def _model_gate():
    """Serialize every call to the one local model, across threads and across processes.

    A fresh descriptor per call means `flock` covers this process's threads and any other
    process alike, so a demo running beside a benchmark queues instead of killing the server.
    """
    if fcntl is None:
        with _THREAD_LOCK:
            yield
        return
    handle = os.open(GATE_PATH, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


class ChoiceRejected(RuntimeError):
    """The answer did not satisfy the choice contract, so it is re-asked, never repaired."""


@dataclass
class Decision:
    choice: str
    probabilities: dict = field(default_factory=dict)
    confidence: float | None = None
    latency_ms: float = 0.0
    attempts: int = 1
    model: str | None = None
    usage: dict = field(default_factory=dict)
    raw_answers: dict = field(default_factory=dict)


def validate_choice(answer, candidates):
    """The typed-choice contract, identical to the one jev's client enforces."""
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in candidates
            and set(probabilities) == set(candidates)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1
                    for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ChoiceRejected("answer does not satisfy the choice contract: %r" % (answer,))
    return answer


def is_up(host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=2.0):
    """Whether the laya server is answering, without loading anything."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b'{"id": 0, "op": "ping"}\n')
            reply = sock.recv(4096)
    except OSError:
        return False
    try:
        return bool(json.loads(reply).get("ok"))
    except ValueError:
        return False


class LayaClient:
    """One choice question per move, over the reused persistent server."""

    def __init__(self, host=None, port=None, timeout=DEFAULT_TIMEOUT, attempts=2, backoff=0.3):
        # The same resolved endpoint the reachability check uses, so a pre-flight can never
        # pass while the client is about to dial somewhere else.
        self.host = host or DEFAULT_HOST
        self.port = int(port or DEFAULT_PORT)
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff
        self.calls = 0
        self.rejections = 0
        self.transport_errors = 0
        self._transport = _Transport(host=self.host, port=self.port, timeout=self.timeout)

    def close(self):
        self._transport.close()

    def ask_sync(self, state, criteria, instructions, question="direction"):
        body = {question: {"type": "choice", "criteria": criteria, "instructions": instructions}}
        total_ms = 0.0
        last_error = None

        for attempt in range(self.attempts):
            started = time.perf_counter()
            try:
                with _model_gate():
                    result = self._transport.ask(state, body)
            except (LayaError, OSError) as exc:
                # A dropped socket or a server-side exception. The question is idempotent, so
                # a retry costs only time; the transport reconnects on the next call.
                self.transport_errors += 1
                last_error = str(exc)
                if attempt + 1 < self.attempts:
                    time.sleep(self.backoff * (attempt + 1))
                continue
            total_ms += (time.perf_counter() - started) * 1000
            self.calls += 1

            answer = (result.get("answers") or {}).get(question, {})
            try:
                validated = validate_choice(answer, criteria)
            except ChoiceRejected as exc:
                self.rejections += 1
                last_error = str(exc)
                if attempt + 1 < self.attempts:
                    time.sleep(self.backoff * (attempt + 1))
                continue

            return Decision(
                choice=validated["choice"],
                probabilities=dict(validated.get("probabilities", {})),
                confidence=validated.get("confidence"),
                latency_ms=round(total_ms, 1),
                attempts=attempt + 1,
                model=result.get("model"),
                usage=result.get("usage", {}) or {},
                raw_answers=result.get("answers", {}),
            )

        raise LayaError("%d attempts failed; last %s" % (self.attempts, last_error))

    async def ask(self, state, criteria, instructions, question="direction"):
        """`ask_sync` on a worker thread.

        The transport is a blocking socket read. Left on the event loop it would serialize
        every concurrent game behind whichever question is in flight, which is the same
        mistake the jev client had to avoid.
        """
        return await asyncio.to_thread(self.ask_sync, state, criteria, instructions, question)
