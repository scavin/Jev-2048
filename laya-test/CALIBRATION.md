# Laya as a 2048 test oracle: what it can and cannot do

Every number here was measured on this machine against the installed
`convaiinnovations/laya` `typed-decisions` checkpoint (encoder `answerdotai/ModernBERT-large`,
MPS). Nothing is inferred from the model card.

## Why Laya cannot be the test runner

Laya answers typed questions (`choice`, `score`, `noul`) about a piece of supplied text. It
does not execute code, browse, or retrieve facts. Testing a game with it therefore means
handing it observations and asking it to classify them — which only works if the
observations are shaped the way the model was trained to read them.

## Latency: the wrapper is unusable in a loop

| Path | Latency |
|---|---|
| `run_laya.py --input …` (checked-in wrapper) | **24.5 s** per call — reloads ModernBERT-large every time |
| `laya_server.py` + `laya_client.py` (persistent) | **0.158 s** per question |

A per-call reload makes a test loop impossible; the persistent server is what makes the
harness viable. It loads the same checkpoint through the same `laya.load` path, and does not
reinstall Laya or download a second checkpoint.

## Evidence length destroys the signal

Two-option question (merge failure vs spawn failure), same key sentence, padded with neutral
filler words:

| Extra filler words | Accuracy | Mean confidence |
|---|---|---|
| 0 | 4/4 | 0.051 |
| 8 | 4/4 | 0.010 |
| 24 | 4/4 | 0.012 |
| 48 | 2/4 | 0.003 |
| 96 | 2/4 | 0.008 |

Above ~40 words of evidence the answer stops depending on the evidence. Confidence is
near-zero even when the answer is right, so **confidence must never be used as a gate**.

## Question families

| Family | Task | Accuracy | Verdict |
|---|---|---|---|
| A | 4x4 number grid → fresh/in-progress/game-over/won | 50% (chance) | unusable |
| B | Same facts as prose → in-progress/game-over | 50% (chance) | unusable |
| C | `noul`: "is this a legal position?" (valid vs corrupt boards) | 50% (chance) | unusable |
| D | 7-way failure triage from a short observation | **71.4%** (chance 14%) | usable, weakly |

Family A is not merely at chance: the model answers `in_progress` for a full board with no
equal neighbours and `won` for a two-tile fresh board. It is not reading the grid. Family C
returns P(legal) = 0.546 for valid boards and 0.560 for boards containing a `3`, a `-2`, or a
`12` — no separation.

## Triage quality depends on how the evidence is phrased

Measured by injecting five real defects into `js/game_manager.js` and asking Laya which
subsystem each failure implicates (`run_tests.py --mutants`):

| Injected defect | Suite detected | Laya's top label | Laya correct |
|---|---|---|---|
| `scoring` (score += pre-merge value) | yes | `scoring` | **100%** of triaged failures |
| `spawn` (two tiles per move) | yes | `spawn` | **100%** of triaged failures |
| `merge` (no once-per-move guard) | yes | `scoring` | 0% |
| `movement` (no reverse traversal) | yes | `spawn` | ~10-18% |
| `game_over_detection` (inverted) | yes | `scoring` | ~5-7% |

(Failure counts vary between runs because tile spawns are random; the fractions are stable
across repeated runs. Reproduce with `run_tests.py --mutants`.)

Laya is reliable exactly when the distilled evidence states a **quantitative** anomaly
("the score rose by 4 instead of 8", "2 new tiles appeared instead of 1"). When the evidence
is a board diff ("the board became X instead of Y"), the three candidate subsystems are
indistinguishable from the text alone, and Laya falls back to a label prior.

## Rules this harness follows

1. **Laya never decides pass/fail.** Deterministic assertions against `reference2048.py` do.
2. **Evidence handed to Laya stays under ~40 words.**
3. **Quantitative evidence is preferred** for triage; board-diff triage is reported but
   marked low-trust.
4. **Confidence is recorded, never thresholded.**
5. **Laya's message-consistency check is a cross-check** whose agreement with the
   deterministic verdict is reported on every run — it is not the verdict.
6. Per the checkpoint's own safety note, triage output is a routing hint for a human or agent,
   not an automated action.
