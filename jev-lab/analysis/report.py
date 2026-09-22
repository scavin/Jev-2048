"""Render the comparison report from benchmark summary files.

    python analysis/report.py                       # every results/*_summary.json
    python analysis/report.py results/a.json ...    # named files

Writes `results/report.md` and prints the table. It only rearranges numbers the benchmark
already computed: no metric is recalculated here, so the report cannot disagree with the
raw JSON it is built from.
"""

import argparse
import glob
import json
import os
import sys

# Runnable as `python analysis/report.py`, so the project root has to be on the path
# before the lab's own modules can be imported.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import labpaths  # noqa: E402

ROWS = (
    ("Mode", "mode", "{}"),
    ("Games", "games", "{}"),
    ("Scored", "games_scored", "{}"),
    ("Abort%", "aborted_pct", "{:.1f}"),
    ("Avg Score", "average_score", "{:.1f}"),
    ("Median", "median_score", "{:.1f}"),
    ("P90", "p90_score", "{:.1f}"),
    ("Max", "max_score", "{}"),
    ("Avg Steps", "average_steps", "{:.1f}"),
    ("Max Tile", "average_max_tile", "{:.1f}"),
    ("256%", "reached_256_pct", "{:.1f}"),
    ("512%", "reached_512_pct", "{:.1f}"),
    ("1024%", "reached_1024_pct", "{:.1f}"),
    ("2048%", "reached_2048_pct", "{:.1f}"),
    ("4096%", "reached_4096_pct", "{:.1f}"),
    ("Invalid%", "invalid_move_rate", "{:.2%}"),
    ("Loop%", "loop_rate", "{:.2%}"),
    ("Repeat%", "repeated_state_rate", "{:.2%}"),
    ("Corner%", "corner_break_rate", "{:.2%}"),
    ("Collapse%", "space_collapse_rate", "{:.2%}"),
    ("Trap%", "greedy_trap_rate", "{:.2%}"),
    ("Stagnation%", "decision_stagnation_rate", "{:.2%}"),
    ("Avg Lat ms", "average_latency_ms", "{:.1f}"),
    ("P50 ms", "p50_latency_ms", "{:.1f}"),
    ("P95 ms", "p95_latency_ms", "{:.1f}"),
)

PROVENANCE = ("tag", "seed", "games", "max_steps", "headless", "workers", "elapsed_s")


def load(path):
    with open(path) as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    if "summaries" in payload:
        return list(payload["summaries"])
    return [payload]


def markdown(summaries, provenance=None):
    lines = []
    if provenance:
        lines.append("Run: " + ", ".join("%s=%s" % (key, provenance[key])
                                         for key in PROVENANCE if key in provenance))
        lines.append("")
    lines.append("| " + " | ".join(label for label, _, _ in ROWS) + " |")
    lines.append("|" + "|".join("---" for _ in ROWS) + "|")
    for summary in summaries:
        cells = []
        for _, key, fmt in ROWS:
            value = summary.get(key)
            if value is None:
                cells.append("--")
            elif fmt == "{}":
                cells.append(str(value))
            elif fmt.endswith("%}"):
                # A rate is stored as a fraction, and `{:.2%}` wants exactly that.
                cells.append(fmt.format(float(value)))
            else:
                cells.append(fmt.format(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="summary JSON files")
    parser.add_argument("--out", default=os.path.join(labpaths.RESULTS_DIR, "report.md"))
    args = parser.parse_args(argv)

    paths = args.paths or sorted(glob.glob(os.path.join(labpaths.RESULTS_DIR, "*_summary.json")))
    if not paths:
        print("no summary files found; run benchmark.py first", file=sys.stderr)
        return 1

    summaries = []
    provenance = None
    for path in paths:
        loaded = load(path)
        summaries.extend(loaded)
        if provenance is None:
            with open(path) as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                provenance = payload
    body = markdown(summaries, provenance)
    with open(args.out, "w") as handle:
        handle.write("# 2048 / jev harness experiment\n\n```\n" + body + "\n```\n")
    print(body)
    print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
