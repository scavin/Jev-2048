"""Aggregation and export for a batch of games.

Rates are per-step unless the name says otherwise: `invalid_move_rate` is the share of
executed moves that the game ignored, `loop_rate` is the share of moves the failure
detector tagged as an alternating loop. `games_with_*_rate` is the share of *games* in
which a tag fired at least once, which is the number that answers "how often does this
failure end a run".
"""

import csv
import json

import labpaths  # noqa: F401

from analysis.failure_detector import TAGS

GAME_FIELDS = [
    "mode", "game_id", "seed", "score", "steps", "max_tile", "ended", "abort_reason",
    "reached_256", "reached_512", "reached_1024", "reached_2048", "reached_4096",
    "invalid_moves", "invalid_move_rate", "latency_avg", "latency_p50", "latency_p95",
    "wall_clock_ms", "jev_calls", "jev_rejections", "tokens_in", "tokens_out",
    "kept_playing", "tag_counts",
]


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = fraction * (len(ordered) - 1)
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def game_row(outcome):
    row = outcome.to_dict()
    row["invalid_move_rate"] = round(outcome.invalid_moves / outcome.steps, 4) if outcome.steps else 0.0
    for tile in (256, 512, 1024, 2048, 4096):
        row["reached_%d" % tile] = bool(row["reached"].get(str(tile)))
    return row


def aggregate(outcomes, mode=None):
    """Everything the benchmark report needs.

    A game the harness aborted (a dropped connection, a page that never loaded) is a
    truncated game, not a result: averaging it in would report the infrastructure's failure
    as the policy's. Aborted games are therefore excluded from the score, step, tile and
    latency statistics, and counted separately as `aborted_games`. Their *steps* are still
    real moves and still count towards the per-step failure rates.
    """
    rows = [game_row(outcome) for outcome in outcomes]
    scored = [row for row in rows if row["ended"] != "aborted"]
    scores = [row["score"] for row in scored]
    steps = [row["steps"] for row in scored]
    latencies = [latency for row in scored for latency in row["latencies"]]
    total_steps = sum(row["steps"] for row in rows)

    summary = {
        "mode": mode or (rows[0]["mode"] if rows else None),
        "games": len(rows),
        "games_scored": len(scored),
        "games_finished": sum(1 for row in rows if row["ended"] == "game_over"),
        "aborted_games": sum(1 for row in rows if row["ended"] == "aborted"),
        "aborted_pct": round(100.0 * sum(1 for row in rows if row["ended"] == "aborted")
                             / len(rows), 1) if rows else 0.0,
        "max_steps_games": sum(1 for row in rows if row["ended"] == "max_steps"),
        "average_score": round(_mean(scores), 1),
        "median_score": round(percentile(scores, 0.5), 1),
        "p90_score": round(percentile(scores, 0.9), 1),
        "max_score": max(scores) if scores else 0,
        "average_steps": round(_mean(steps), 1),
        "median_steps": round(percentile(steps, 0.5), 1),
        "average_max_tile": round(_mean([row["max_tile"] for row in scored]), 1),
        "average_latency_ms": round(_mean(latencies), 1),
        "p50_latency_ms": round(percentile(latencies, 0.5), 1),
        "p95_latency_ms": round(percentile(latencies, 0.95), 1),
        "average_wall_clock_ms": round(_mean([row["wall_clock_ms"] for row in rows]), 1),
        "invalid_move_rate": round(sum(row["invalid_moves"] for row in rows) / total_steps, 4)
        if total_steps else 0.0,
        "jev_calls": sum(row["jev_calls"] for row in rows),
        "jev_rejections": sum(row["jev_rejections"] for row in rows),
        "tokens_in": sum(row["tokens_in"] for row in rows),
        "tokens_out": sum(row["tokens_out"] for row in rows),
    }

    for tile in (256, 512, 1024, 2048, 4096):
        hits = sum(1 for row in scored if row["reached_%d" % tile])
        summary["reached_%d_pct" % tile] = round(100.0 * hits / len(scored), 1) if scored else 0.0

    for tag in TAGS:
        tagged_steps = sum(row["tag_counts"].get(tag, 0) for row in rows)
        tagged_games = sum(1 for row in rows if row["tag_counts"].get(tag, 0))
        summary["%s_rate" % tag] = round(tagged_steps / total_steps, 4) if total_steps else 0.0
        summary["games_with_%s_rate" % tag] = round(tagged_games / len(rows), 4) if rows else 0.0

    # The headline "loop rate" is the alternating-loop detector's rate; it is the one that
    # shows up in the comparison table. Kept as its own key so the table never has to know
    # which detector stands for looping.
    summary["loop_rate"] = summary["alternating_loop_rate"]
    return summary


def write_json(path, payload):
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return path


def write_csv(path, rows, fields):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})
    return path


def summary_fields():
    return list(aggregate([]).keys())


COLUMNS = ("mode", "games", "games_scored", "aborted_pct", "average_score", "median_score",
           "p90_score", "max_score", "average_steps", "average_max_tile",
           "reached_256_pct", "reached_512_pct", "reached_1024_pct", "reached_2048_pct",
           "reached_4096_pct", "invalid_move_rate", "loop_rate", "repeated_state_rate",
           "corner_break_rate", "average_latency_ms", "p50_latency_ms", "p95_latency_ms")


def comparison_table(summaries):
    """The final table. No expected winner is encoded anywhere in it."""
    header = ("Mode", "Games", "Scored", "Abort%", "Avg Score", "Median", "P90", "Max",
              "Avg Steps", "Max Tile", "256%", "512%", "1024%", "2048%", "4096%",
              "Invalid%", "Loop%", "Repeat%", "Corner%", "Lat ms", "P50 ms", "P95 ms")
    keys = COLUMNS
    lines = ["  ".join("%-11s" % cell for cell in header),
             "  ".join("-" * 11 for _ in header)]
    for summary in summaries:
        cells = []
        for key in keys:
            value = summary.get(key)
            if key.endswith("_rate") or key == "aborted_pct":
                cells.append("%.1f%%" % (100.0 * value if key.endswith("_rate") else value))
            elif isinstance(value, float):
                cells.append("%.1f" % value)
            else:
                cells.append(str(value))
        lines.append("  ".join("%-11s" % cell for cell in cells))
    return "\n".join(lines)
