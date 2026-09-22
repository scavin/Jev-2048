"""Laya as a judge inside the 2048 test loop.

Scope is set by measurement, not by hope (see calibrate.py and CALIBRATION.md):

  * a 2-option question over evidence up to ~40 words discriminates reliably;
  * a 7-option question over the same evidence still carries signal, but weakly;
  * evidence longer than ~50 words collapses the signal to chance;
  * the model cannot read a 4x4 number grid at all (50% on a 4-way question);
  * `confidence` stays near 0 even on correct answers, so it is never used as a gate.

Therefore Laya never decides pass/fail here. It answers "which subsystem does this
observation implicate?" and "does the shown message match the board?" — questions whose
ground truth the suite already knows, so agreement is measurable on every run.
"""

TRIAGE_OPTIONS = {
    "movement": "tiles end up in the wrong cells after a slide",
    "merge": "two tiles combine incorrectly, or one tile appears twice in a cell",
    "scoring": "the score does not equal the sum of the merged tile values",
    "spawn": "the wrong number of new tiles appears after a move",
    "game_over_detection": "the win or loss state is wrong for the board",
    "persistence": "the stored game state or best score is wrong after a reload",
    "rendering": "the DOM disagrees with the board model",
}

TRIAGE_INSTRUCTIONS = "Which part of the 2048 implementation does this observation implicate?"

MESSAGE_OPTIONS = {
    "matches": "the message is correct for the board described",
    "contradicts": "the message is wrong for the board described",
}


def _fmt_board(board):
    return " ".join("[" + ",".join(str(v) for v in row) + "]" for row in board)


def triage_evidence(kind, direction_name=None, **fields):
    """One sentence, under ~40 words, naming the anomaly and nothing else.

    Long evidence measurably destroys the signal, so the harness must hand Laya a
    distilled observation rather than a dump of the whole test record.
    """
    if kind == "board_mismatch":
        return ("After Arrow%s the board became %s instead of %s."
                % (direction_name, _fmt_board(fields["actual"]), _fmt_board(fields["expected"])))
    if kind == "score_mismatch":
        return ("After Arrow%s the score rose by %d instead of %d."
                % (direction_name, fields["actual_delta"], fields["expected_delta"]))
    if kind == "spawn_count":
        return ("After Arrow%s, %d new tiles appeared on the board instead of 1."
                % (direction_name, fields["spawned"]))
    if kind == "no_op_changed":
        return ("After Arrow%s no tile could move, yet the board changed from %s to %s."
                % (direction_name, _fmt_board(fields["before"]), _fmt_board(fields["after"])))
    if kind == "spawn_value":
        return ("After Arrow%s a new tile showing %d appeared; new tiles must show 2 or 4."
                % (direction_name, fields["value"]))
    if kind == "dom_model_mismatch":
        return ("The board model holds %s but the rendered tiles show %s."
                % (_fmt_board(fields["model"]), _fmt_board(fields["dom"])))
    if kind == "message_missing":
        return ("The grid is full with no equal neighbours, yet no game over message is shown.")
    if kind == "message_wrong":
        return ("The page shows %r while the board still allows moves." % fields["message"])
    if kind == "restart_residue":
        return ("After New Game the board holds %d tiles and the score reads %d."
                % (fields["tiles"], fields["score"]))
    if kind == "persistence_board":
        return ("After reloading the page the board came back as %s instead of %s."
                % (_fmt_board(fields["actual"]), _fmt_board(fields["expected"])))
    if kind == "persistence_score":
        return ("After reloading the page the score came back as %d instead of %d."
                % (fields["actual"], fields["expected"]))
    if kind == "best_below_score":
        return ("The best score reads %d while the current score reads %d."
                % (fields["best"], fields["score"]))
    if kind == "best_regressed":
        return ("The best score reads %d after New Game, down from %d before it."
                % (fields["after_best"], fields["before_best"]))
    if kind == "state_not_cleared":
        return "The game is over but the page still stores a saved game state."
    if kind == "illegal_tile":
        return ("The board holds a tile showing %d, which is not a power of two of at least 2."
                % fields["value"])
    if kind == "keep_playing_blocked":
        return ("After Keep going the game still refuses to move any tile.")
    return "The 2048 game produced an observation that does not match the rules."


def triage(laya, evidence):
    result = laya.ask(evidence, {"q": {"type": "choice",
                                       "instructions": TRIAGE_INSTRUCTIONS,
                                       "criteria": TRIAGE_OPTIONS}})
    answer = result["answers"]["q"]
    return {"subsystem": answer.get("choice"),
            "probabilities": answer.get("probabilities"),
            "confidence": answer.get("confidence")}


def message_evidence(snapshot, moves_possible, message):
    """Short, board-descriptive evidence for the message-consistency question.

    The largest tile has to be in here: without it the win prompt is unjudgeable, and a
    question the evidence cannot answer would be measuring nothing.
    """
    values = [v for row in snapshot["board"] for v in row if v]
    empties = 16 - len(values)
    adjacency = ("At least two tiles that share an edge show the same value." if moves_possible
                 else "No two tiles that share an edge show the same value.")
    return ("The 4x4 grid holds %d tiles and %d empty cells remain. The largest tile shows %d. %s "
            "The page shows the message %r."
            % (len(values), empties, max(values) if values else 0, adjacency, message))


def judge_message(laya, snapshot, moves_possible, message):
    result = laya.ask(message_evidence(snapshot, moves_possible, message),
                      {"q": {"type": "choice",
                             "instructions": "Does the message shown by the page match the board?",
                             "criteria": MESSAGE_OPTIONS}})
    answer = result["answers"]["q"]
    return {"verdict": answer.get("choice"),
            "probabilities": answer.get("probabilities"),
            "confidence": answer.get("confidence")}
