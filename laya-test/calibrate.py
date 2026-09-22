"""Calibrate Laya against known 2048 facts before trusting it in a test loop.

Laya is a typed-decision model, not an executor: it can only classify evidence we
hand it. This script measures, per question family, whether the evidence actually
moves the answer. A family whose accuracy sits at chance is unusable as an oracle
no matter how confident the model sounds.

Run:  python laya-test/calibrate.py [--cases 60]
"""

import argparse
import collections
import json
import random
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import reference2048 as ref  # noqa: E402
from laya_client import LayaClient  # noqa: E402

BOARD_OPTIONS = {
    "fresh_start": "exactly the two starting tiles are on the board and the score is 0",
    "in_progress": "at least one move can still change the board and no win or loss message is shown",
    "game_over": "every cell is filled and no two edge-adjacent tiles share a value, so no move can change the board",
    "won": "a win message is shown because the 2048 tile was reached",
}


# --------------------------------------------------------------------------- cases


def random_play_board(rng, plies):
    board, _ = ref.new_game(rng)
    for _ in range(plies):
        direction = rng.randrange(4)
        board2, _, moved = ref.move(board, direction)
        if moved:
            board = board2
            ref.spawn(board, rng)
        if not ref.moves_available(board):
            break
    return board


def dead_board(rng):
    """Full board with no equal edge-neighbours, and therefore no legal move."""
    pattern = [[2, 4, 8, 16], [4, 8, 16, 2], [8, 16, 2, 4], [16, 2, 4, 8]]
    if rng.random() < 0.5:
        pattern = [row[::-1] for row in pattern]
    return ref.from_rows(pattern)


def won_board(rng):
    board = random_play_board(rng, rng.randrange(40, 120))
    board[rng.randrange(4)][rng.randrange(4)] = 2048
    return board


def board_cases(rng, count):
    """Family A: the raw serialization a harness can capture from the real game."""
    cases = []
    for i in range(count):
        kind = ("fresh_start", "in_progress", "game_over", "won")[i % 4]
        if kind == "fresh_start":
            board, _ = ref.new_game(rng)
            board = ref.new_board()
            board[0][0], board[3][3] = 2, 4
            score, message = 0, ""
        elif kind == "in_progress":
            board = random_play_board(rng, rng.randrange(4, 60))
            if not ref.moves_available(board):
                continue
            score, message = rng.randrange(4, 3000), ""
        elif kind == "game_over":
            board, score, message = dead_board(rng), rng.randrange(100, 9000), ""
        else:
            board, score, message = won_board(rng), rng.randrange(1000, 20000), "You win!"

        evidence = (
            "board 4x4, rows top to bottom: %s; empty cells: %d; score: %d; message shown: %s"
            % (ref.render_rows(board), len(ref.empty_cells(board)), score, message or "none")
        )
        cases.append({"kind": kind, "board": board, "evidence": evidence})
    return cases


def summary_cases(rng, count):
    """Family B: the same facts pre-digested into prose instead of a number grid."""
    cases = []
    for i in range(count):
        kind = ("in_progress", "game_over")[i % 2]
        if kind == "game_over":
            board = dead_board(rng)
            evidence = ("The 4x4 grid holds %d tiles and no empty cells remain. No two tiles that share "
                        "an edge show the same value. No win or loss message is shown." % len(ref.tiles(board)))
        else:
            board = random_play_board(rng, rng.randrange(4, 60))
            if not ref.moves_available(board):
                continue
            free = len(ref.empty_cells(board))
            if ref.merge_exists(board):
                detail = "At least two tiles that share an edge show the same value."
            else:
                detail = "No two tiles that share an edge show the same value."
            evidence = ("The 4x4 grid holds %d tiles and %d empty cells remain. %s "
                        "No win or loss message is shown." % (len(ref.tiles(board)), free, detail))
        cases.append({"kind": kind, "board": board, "evidence": evidence})
    return cases


CORRUPT = [
    "board 4x4, rows top to bottom: [2,4,2,4] [4,2,4,3] [2,4,2,4] [4,2,4,2]; empty cells: 0; score: 1024; message shown: none",
    "board 4x4, rows top to bottom: [2,4,2,4] [4,2,4,2] [2,4,2,6] [4,2,4,2]; empty cells: 0; score: 1024; message shown: none",
    "board 4x4, rows top to bottom: [2,4,2,4] [4,2,4,2] [2,4,2,4] [4,2,4,-2]; empty cells: 0; score: 1024; message shown: none",
    "board 4x4, rows top to bottom: [2,4,2,4] [4,2,4,2] [2,4,2,4] [4,2,4,12]; empty cells: 0; score: 1024; message shown: none",
]
VALID = [
    "board 4x4, rows top to bottom: [2,4,2,4] [4,2,4,2] [2,4,2,4] [4,2,4,2]; empty cells: 0; score: 1024; message shown: none",
    "board 4x4, rows top to bottom: [2,0,0,0] [0,0,0,0] [0,0,0,0] [0,0,0,4]; empty cells: 14; score: 0; message shown: none",
    "board 4x4, rows top to bottom: [2,4,8,16] [0,0,0,0] [0,0,0,0] [0,0,0,0]; empty cells: 12; score: 12; message shown: none",
    "board 4x4, rows top to bottom: [2,2,4,8] [0,0,0,0] [0,0,0,0] [0,0,0,0]; empty cells: 12; score: 0; message shown: none",
]

TRIAGE = [
    ("After ArrowLeft the score rose by 4, but the board still shows an 8 tile and a second 8 tile in the same cell (x=3, y=0).", "merge"),
    ("After ArrowDown the board shows three tiles where two should be, and two of them overlap in the same cell.", "merge"),
    ("After ArrowRight every tile slid correctly and a new tile appeared, but the score did not change even though a 4 and a 4 merged.", "scoring"),
    ("After ArrowUp a 16 and a 16 merged into 32 and the score rose by 16 instead of 32.", "scoring"),
    ("After ArrowLeft the score rose by 8, but two new tiles appeared on the board instead of one.", "spawn"),
    ("After a move that changed nothing, a new tile appeared anyway.", "spawn"),
    ("After ArrowRight a tile ended up two cells away from where the same slide places it in the reference engine.", "movement"),
    ("After ArrowUp the tiles ended up at the bottom of the board instead of the top.", "movement"),
    ("The board has no empty cells and no equal neighbours, yet no game over message appeared and arrow keys still change nothing.", "game_over_detection"),
    ("The game over message is shown while an empty cell and a merge are still available.", "game_over_detection"),
    ("After reloading the page the score reset to 0 even though the best score was kept.", "persistence"),
    ("After reloading the page the board came back with tiles in different cells than before the reload.", "persistence"),
    ("The board model holds four tiles but only three tile elements are visible on screen.", "rendering"),
    ("A tile element stays at its old position after the board model has already moved it.", "rendering"),
]

TRIAGE_OPTIONS = {
    "movement": "tiles end up in the wrong cells after a slide",
    "merge": "two tiles combine incorrectly, or one tile appears twice in a cell",
    "scoring": "the score does not equal the sum of the merged tile values",
    "spawn": "the wrong number of new tiles appears after a move",
    "game_over_detection": "the win or loss state is wrong for the board",
    "persistence": "the stored game state or best score is wrong after a reload",
    "rendering": "the DOM disagrees with the board model",
}


# --------------------------------------------------------------------------- runner


def predicted_label(answer):
    """choice -> the chosen label; noul -> thresholded P(true) (there is no 'choice' field)."""
    if answer.get("type") == "noul":
        return "true" if answer.get("noul", 0.0) >= 0.5 else "false"
    return answer.get("choice")


def score_family(laya, cases, questions_fn, truth_fn):
    rows = []
    for case in cases:
        result = laya.ask(case["evidence"], questions_fn(case))
        answer = result["answers"]["q"]
        rows.append({
            "expected": truth_fn(case),
            "got": predicted_label(answer),
            "confidence": answer.get("confidence"),
            "probabilities": answer.get("probabilities") or {"P(true)": answer.get("noul")},
            "evidence": case["evidence"],
        })
    return rows


def report(name, rows):
    correct = sum(1 for r in rows if r["expected"] == r["got"])
    total = len(rows)
    conf = sum(r["confidence"] or 0 for r in rows) / total if total else 0
    print("\n=== %s ===  accuracy %d/%d = %.1f%%   mean confidence %.3f"
          % (name, correct, total, 100.0 * correct / total if total else 0.0, conf))
    confusion = collections.Counter((r["expected"], r["got"]) for r in rows)
    for (expected, got), n in sorted(confusion.items(), key=lambda kv: -kv[1]):
        flag = "" if expected == got else "   <-- wrong"
        print("   %-18s -> %-18s %2d%s" % (expected, got, n, flag))
    return correct, total, conf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=60)
    parser.add_argument("--seed", type=int, default=2048)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    laya = LayaClient()

    board_q = {"q": {"type": "choice",
                     "instructions": "Classify the state of this 2048 board.",
                     "criteria": BOARD_OPTIONS}}
    summary_q = {"q": {"type": "choice",
                       "instructions": "Classify the state of this 2048 board.",
                       "criteria": {"in_progress": BOARD_OPTIONS["in_progress"],
                                    "game_over": BOARD_OPTIONS["game_over"]}}}
    valid_q = {"q": {"type": "noul",
                     "instructions": "The board is a legal 2048 position: every tile is a power of two and at least 2.",
                     "criteria": {"true": "every tile is a power of two and at least 2",
                                  "false": "at least one tile is not a power of two or is below 2"}}}
    triage_q = {"q": {"type": "choice",
                      "instructions": "Which part of the 2048 implementation does this observation implicate?",
                      "criteria": TRIAGE_OPTIONS}}

    a_cases = board_cases(rng, args.cases)
    b_cases = summary_cases(rng, args.cases)
    v_cases = [{"evidence": e, "kind": "valid"} for e in VALID] + \
              [{"evidence": e, "kind": "corrupt"} for e in CORRUPT]
    t_cases = [{"evidence": e, "kind": k} for e, k in TRIAGE]

    results = {}
    results["A: board grid -> state"] = report(
        "A: board grid -> state", score_family(laya, a_cases, lambda c: board_q, lambda c: c["kind"]))
    results["B: prose summary -> state"] = report(
        "B: prose summary -> state", score_family(laya, b_cases, lambda c: summary_q, lambda c: c["kind"]))
    results["C: legal position? (noul)"] = report(
        "C: legal position? (noul)",
        score_family(laya, v_cases, lambda c: valid_q,
                     lambda c: "true" if c["kind"] == "valid" else "false"))
    results["D: failure triage"] = report(
        "D: failure triage", score_family(laya, t_cases, lambda c: triage_q, lambda c: c["kind"]))

    with open("/tmp/laya2048/calibration.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nwrote /tmp/laya2048/calibration.json")


if __name__ == "__main__":
    main()
