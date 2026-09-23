"""The shared base for the two model-backed policies.

The experiment has two axes now. The **state design** is the one being measured and is shared
by both models; the **model** is the other axis and is the only thing a subclass changes.
`name` is derived from the pair, so a mode string always says which model decided and what it
was shown: `laya-features` is laya, given the harness's one-ply simulation.
"""

import labpaths  # noqa: F401

import prompts
from players.base import Decision, Player


class ModelPlayer(Player):
    model = ""              # "jev" or "laya"
    design = "board"        # one of prompts.DESIGNS
    uses_jev = True

    def __init__(self, seed=0, client=None, attempts=4):
        super().__init__(seed)
        self.client = client or self.make_client(attempts=attempts)

    @property
    def name(self):
        return "%s-%s" % (self.model, self.design)

    def make_client(self, attempts=4):
        raise NotImplementedError

    def build_prompt(self, ctx):
        return prompts.build(prompts.Context(
            design=self.design,
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
            source=self.name,
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
