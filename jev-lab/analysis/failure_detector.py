"""Failure detectors. They mark steps; they never change a step.

Seven patterns are checked, all of them visible from the harness side alone:

1. `alternating_loop`      — two directions alternating for a run of moves
2. `repeated_state`        — the same board shape (up to rotation and mirroring) returning
3. `invalid_repetition`    — the same illegal direction chosen again and again
4. `corner_break`          — the largest tile leaving a corner it had held for a while
5. `space_collapse`        — empty cells draining away in a short window
6. `greedy_trap`           — score climbing while the board structure gets worse
7. `decision_stagnation`   — the same direction over and over with nothing to show for it

An eighth tag, `harness_desync`, is not a jev failure: it fires when the simulator's
verdict on legality and the page's actual reaction disagree, which would mean the harness
is wrong about the game.

Every tag is recorded next to the step that earned it. No detector ever overrides a
choice — the runner has no code path that turns a tag into a move.
"""

from dataclasses import dataclass, field

import labpaths  # noqa: F401

CHECK_LABELS = {
    "alternating_loop": "Loop",
    "repeated_state": "Repeated State",
    "invalid_repetition": "Invalid Repeat",
    "corner_break": "Corner Break",
    "space_collapse": "Space Collapse",
    "greedy_trap": "Greedy Trap",
    "decision_stagnation": "Stagnation",
    "harness_desync": "Harness Desync",
}

TAGS = tuple(CHECK_LABELS)


@dataclass
class Detection:
    tags: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)


class FailureDetector:
    def __init__(self, alternating_run=6, state_window=20, state_repeats=3,
                 invalid_window=10, invalid_repeats=2, corner_dwell=5,
                 collapse_window=10, collapse_drop=6, collapse_floor=2,
                 trap_window=8, trap_score=32, trap_mono_drop=0.15, trap_space_drop=4,
                 stagnation_run=4, warmup=8):
        self.alternating_run = alternating_run
        self.state_window = state_window
        self.state_repeats = state_repeats
        self.invalid_window = invalid_window
        self.invalid_repeats = invalid_repeats
        self.corner_dwell = corner_dwell
        self.collapse_window = collapse_window
        self.collapse_drop = collapse_drop
        self.collapse_floor = collapse_floor
        self.trap_window = trap_window
        self.trap_score = trap_score
        self.trap_mono_drop = trap_mono_drop
        self.trap_space_drop = trap_space_drop
        self.stagnation_run = stagnation_run
        self.warmup = warmup
        self.records = []
        self.tally = {tag: 0 for tag in TAGS}

    # ------------------------------------------------------------------ helpers

    def _recent(self, count):
        """The last `count` records, including the one being judged."""
        return self.records[-count:]

    def _corner_run(self):
        """How many steps before the current one the largest tile held one corner."""
        run = 0
        for item in reversed(self.records[:-1]):
            if not item.get("largest_corner"):
                break
            run += 1
        return run

    # ------------------------------------------------------------------ detectors

    def _alternating(self):
        run = self.alternating_run
        actions = [record["action"] for record in self._recent(run)]
        if len(actions) < run:
            return False, {}
        pairs = {actions[i] for i in range(len(actions))}
        alternates = all(actions[i] != actions[i - 1] for i in range(1, len(actions))) and \
            all(actions[i] == actions[i - 2] for i in range(2, len(actions)))
        if alternates and len(pairs) == 2:
            return True, {"run": run, "pair": sorted(pairs)}
        return False, {}

    def _repeated_state(self, record):
        if len(self.records) < self.warmup:
            return False, {}
        window = self._recent(self.state_window)
        key = record.get("state_hash")
        same_shape = sum(1 for item in window if item.get("state_hash") == key)
        same_exact = sum(1 for item in window if item["board_hash"] == record["board_hash"])
        if same_shape >= self.state_repeats or same_exact >= self.state_repeats:
            return True, {"same_shape": same_shape, "same_exact": same_exact,
                          "window": len(window)}
        return False, {}

    def _invalid_repetition(self, record):
        if record["action_valid"]:
            return False, {}
        window = self._recent(self.invalid_window)
        same = sum(1 for item in window
                   if item["action"] == record["action"] and not item["action_valid"])
        if same >= self.invalid_repeats:
            return True, {"direction": record["action"], "count": same}
        return False, {}

    def _corner_break(self, record):
        held = self._corner_run()
        if record.get("largest_corner_after") is None and held >= self.corner_dwell:
            return True, {"held_steps": held}
        return False, {}

    def _space_collapse(self, record):
        window = self._recent(self.collapse_window)
        if len(window) < self.collapse_window:
            return False, {}
        series = [item["empty_cells"] for item in window]
        drop = series[0] - series[-1]
        monotone = all(series[i] >= series[i + 1] for i in range(len(series) - 1))
        if drop >= self.collapse_drop and monotone and series[-1] <= self.collapse_floor:
            return True, {"drop": drop, "from": series[0], "to": series[-1]}
        return False, {}

    def _greedy_trap(self, record):
        window = self._recent(self.trap_window)
        if len(window) < self.trap_window:
            return False, {}
        gained = sum(item["score_gain"] for item in window)
        mono_before = window[0].get("monotonicity")
        mono_now = record.get("monotonicity")
        space_drop = window[0]["empty_cells"] - record["empty_cells"]
        structure_lost = (mono_before is not None and mono_now is not None
                          and mono_before - mono_now >= self.trap_mono_drop) or \
            space_drop >= self.trap_space_drop
        if gained >= self.trap_score and structure_lost:
            return True, {"score_gained": gained, "monotonicity_drop":
                          round((mono_before or 0) - (mono_now or 0), 3),
                          "space_drop": space_drop}
        return False, {}

    def _stagnation(self):
        run = self.stagnation_run
        window = self._recent(run)
        if len(window) < run:
            return False, {}
        actions = {item["action"] for item in window}
        if len(actions) != 1:
            return False, {}
        barren = all(not item["action_valid"] for item in window) or \
            sum(item["score_gain"] for item in window) == 0
        if barren:
            return True, {"action": window[-1]["action"], "run": run}
        return False, {}

    def _desync(self, record):
        if record.get("page_reacted") is None:
            return False, {}
        if bool(record["action_valid"]) != bool(record["page_reacted"]):
            return True, {"simulator_valid": record["action_valid"],
                          "page_reacted": record["page_reacted"]}
        return False, {}

    # ------------------------------------------------------------------ entry point

    def observe(self, record):
        """File the record, then check every pattern against it.

        The record is filed first so each window includes the move being judged: a detector
        that needs eight steps of evidence should fire on the eighth, not the ninth.
        """
        self.records.append(record)
        found = {}
        details = {}
        for tag, detector in (("alternating_loop", self._alternating),
                              ("repeated_state", lambda: self._repeated_state(record)),
                              ("invalid_repetition", lambda: self._invalid_repetition(record)),
                              ("corner_break", lambda: self._corner_break(record)),
                              ("space_collapse", lambda: self._space_collapse(record)),
                              ("greedy_trap", lambda: self._greedy_trap(record)),
                              ("decision_stagnation", self._stagnation),
                              ("harness_desync", lambda: self._desync(record))):
            hit, detail = detector()
            found[tag] = hit
            if hit:
                details[tag] = detail
                self.tally[tag] += 1

        return Detection(tags=[tag for tag in TAGS if found[tag]],
                         checks={CHECK_LABELS[tag]: found[tag] for tag in TAGS},
                         details=details)

    def summary(self):
        return {
            "steps": len(self.records),
            "tag_counts": dict(self.tally),
            "games_tags": sorted(tag for tag, count in self.tally.items() if count),
        }
