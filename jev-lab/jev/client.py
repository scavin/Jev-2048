"""The only decision layer: one TypeSafe request per move, over jev's shipped HTTP path.

`post_json` and `validate_choice` come from `jev_ultrafast/model.py` — the same two
functions the browser agent uses — so a decision here travels the same code as a decision
there. `jev-test/jev_client.py` supplies the loader that imports that module without
pulling in the browser agent, and the `.env` reader.

Nothing in this file decides anything. It sends state, and returns what came back.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field

import labpaths  # noqa: F401

from jev_client import load_env, load_model_module  # noqa: E402  (the reused loader)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class JevError(RuntimeError):
    """The model never returned a usable answer. The caller records this; it never guesses."""


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
    request: dict = field(default_factory=dict)

    def ranked(self):
        """The probabilities in descending order, for logs and the dashboard."""
        return sorted(self.probabilities.items(), key=lambda item: -item[1])


class JevClient:
    """One request, one validated choice, with a bounded retry on a malformed answer."""

    def __init__(self, model=None, attempts=4, backoff=0.3):
        load_env()
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise JevError("TYPESAFE_API_KEY missing (see %s/.env)" % labpaths.JEV_REPO)
        module = load_model_module()
        self._post_json = module.post_json
        self._validate_choice = module.validate_choice
        self.model = model or os.environ.get("TYPESAFE_MODEL", "jev-latest")
        self.attempts = attempts
        self.backoff = backoff
        self.calls = 0
        self.rejections = 0
        self.transient_errors = 0

    def build_body(self, state, criteria, instructions, question="direction"):
        return {
            "model": self.model,
            "state": state,
            "questions": {
                question: {
                    "type": "choice",
                    "criteria": criteria,
                    "instructions": instructions,
                }
            },
        }

    def ask_sync(self, state, criteria, instructions, question="direction"):
        """One blocking request-and-validate cycle. Raises JevError if it never validates.

        jev's own validator is strict: exact key set, probabilities in [0, 1] summing to 1,
        and the declared choice as argmax. A response that fails any of those is re-asked
        rather than repaired, and the rejection count is itself a reliability measurement.
        """
        body = self.build_body(state, criteria, instructions, question)
        total_ms = 0.0
        last_error = None
        transient = 0

        for attempt in range(self.attempts):
            started = time.perf_counter()
            try:
                result = self._post_json(ENDPOINT, os.environ["TYPESAFE_API_KEY"], body)
            except RuntimeError as exc:
                # jev's `post_json` gives up on a connection error without retrying, which
                # under a concurrent batch turns one dropped connection into a dead game.
                # The request is idempotent, so a retry costs nothing but time.
                transient += 1
                self.transient_errors += 1
                last_error = str(exc)
                if attempt + 1 < self.attempts:
                    time.sleep(self.backoff * (attempt + 1))
                continue
            total_ms += (time.perf_counter() - started) * 1000
            self.calls += 1

            answer = result.get("answers", {}).get(question, {})
            try:
                validated = self._validate_choice(answer, criteria)
            except ValueError as exc:
                self.rejections += 1
                last_error = "%s: %r" % (exc, answer)
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
                request=body,
            )

        raise JevError("%d attempts failed (%d of them without a response); last %s"
                       % (self.attempts, transient, last_error))

    async def ask(self, state, criteria, instructions, question="direction"):
        """`ask_sync` on a worker thread.

        jev's shipped `post_json` is a blocking `httpx.Client` call. Left on the event loop
        it serializes every game in a batch — six "concurrent" games each waited behind the
        other five, and the batch ran six times slower than the model did. The call itself,
        and therefore the measured latency, is unchanged; only the thread it blocks is.
        """
        return await asyncio.to_thread(self.ask_sync, state, criteria, instructions, question)
