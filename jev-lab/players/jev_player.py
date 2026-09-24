"""One jev player, parameterised by the mode that decides what it is shown.

The four modes are four subclasses of this class with a different `mode` string. They share
one client, one retry policy and one request shape, because the experiment holds the model
fixed and varies only the state.
"""

import labpaths  # noqa: F401

from jev import prompts
from jev.client import JevClient
from players.base import Decision, Player


class JevPlayer(Player):
    mode = "jev-board"
    uses_jev = True

    def __init__(self, seed=0, client=None, model=None, attempts=4):
        super().__init__(seed)
        self.client = client or JevClient(model=model, attempts=attempts)

    def build_prompt(self, ctx):
        return prompts.build(prompts.Context(
            mode=self.mode,
            board=ctx.board,
            score=ctx.score,
            step=ctx.step,
            max_tile=ctx.max_tile,
            empty_cells=ctx.empty_cells,
            last_move=ctx.last_move,
            recent_moves=list(ctx.recent_moves),
            recent_actions=list(ctx.recent_actions),
            recent_boards=list(ctx.recent_boards),
            recent_invalid=list(ctx.recent_invalid),
            pattern_repeats=ctx.pattern_repeats,
            features=ctx.features,
            failure_flags=dict(ctx.failure_flags),
        ))

    async def choose(self, ctx):
        prompt = self.build_prompt(ctx)
        answer = await self.client.ask(prompt.state, prompt.criteria, prompt.instructions)
        return Decision(
            name=answer.choice,
            source=self.mode,
            probabilities=answer.probabilities,
            confidence=answer.confidence,
            latency_ms=answer.latency_ms,
            attempts=answer.attempts,
            model=answer.model,
            usage=answer.usage,
            prompt_text=prompt.text,
            request_state=prompt.state,
            features=ctx.features or None,
            detail={"raw_answers": answer.raw_answers},
        )
