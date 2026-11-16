"""Compare per-case efficiency between two ledger runs.

    uv run python tools/efficiency_report.py results/runs/A.json results/runs/B.json
        [--cases-dir cases/v2] [--metric latency_s ...]

Prints Markdown: for each metric, the median and the p90 of each run and the
delta (B minus A), over all shared cases and then for each case group. The
metrics are `latency_s` and the `efficiency` fields of a ledger entry (model
calls, tool calls, answer words and chars, input and output tokens). See
"Efficiency metrics" in results/README.md.

Only the uids present in both runs are used (rows flagged `stale_case` are
left out). A metric counts for a uid only when both runs have a value for it.
The others are skipped and counted in the `skipped` column: old run files
have no `efficiency` object, tokens may be null, and a row with an `error`
has no usable measurement.

A case with several trials contributes the median of its trials. A run
without `trials` contributes the entry's own value. Case groups come from
the case store; a uid the store no longer holds goes in `(unknown group)`.

These numbers are info-only. They never gate and never change a verdict. Two
runs of the same build differ by a noise floor: run an A/A pair first, and
do not read a delta smaller than that difference as a result.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.efficiency import METRICS
from goldset.ledger import read_run
from goldset.store import load_store

DEFAULT_CASES_DIR = Path(__file__).resolve().parents[1] / "cases" / "v2"
ALL_METRICS = ("latency_s", *METRICS)
UNKNOWN_GROUP = "(unknown group)"


def _entry_value(source: dict, metric: str):
    if metric == "latency_s":
        return source.get("latency_s")
    return (source.get("efficiency") or {}).get(metric)


def case_value(entry: dict, metric: str) -> float | None:
    """One number for a case: the median over trials, else the entry value.

    None when the row errored or no source has a value.
    """
    if entry.get("error"):
        return None
    values = [_entry_value(t, metric) for t in entry.get("trials") or []]
    values = [v for v in values if v is not None]
    if not values:
        value = _entry_value(entry, metric)
        return None if value is None else float(value)
    return float(statistics.median(values))


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile, q in [0, 100]."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q / 100
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _active(run: dict) -> dict[str, dict]:
    return {
        e["uid"]: e for e in run["results"] if e.get("uid") and not e.get("stale_case")
    }


def group_map(cases_dir: Path) -> dict[str, str]:
    try:
        return {uid: case.group for _p, case, uid in load_store(cases_dir)}
    except (OSError, ValueError):
        return {}


def summarise(
    a_entries: dict[str, dict],
    b_entries: dict[str, dict],
    uids: list[str],
    metric: str,
) -> dict:
    """Paired statistics for one metric over ``uids``."""
    pairs = []
    for uid in uids:
        a = case_value(a_entries[uid], metric)
        b = case_value(b_entries[uid], metric)
        if a is not None and b is not None:
            pairs.append((a, b))
    result: dict = {
        "shared": len(uids),
        "n": len(pairs),
        "skipped": len(uids) - len(pairs),
    }
    if pairs:
        a_vals = [p[0] for p in pairs]
        b_vals = [p[1] for p in pairs]
        result.update(
            median_a=statistics.median(a_vals),
            median_b=statistics.median(b_vals),
            p90_a=percentile(a_vals, 90),
            p90_b=percentile(b_vals, 90),
        )
    return result


def _num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.1f}"


def _delta(a: float | None, b: float | None) -> str:
    if a is None or b is None:
        return "-"
    diff = b - a
    pct = f" ({diff / a * 100:+.0f}%)" if a else ""
    sign = "+" if diff > 0 else ""
    return f"{sign}{_num(diff)}{pct}"


def _row(label: str, s: dict) -> str:
    return (
        f"| {label} | {s['n']} | {s['skipped']} "
        f"| {_num(s.get('median_a'))} | {_num(s.get('median_b'))} "
        f"| {_delta(s.get('median_a'), s.get('median_b'))} "
        f"| {_num(s.get('p90_a'))} | {_num(s.get('p90_b'))} "
        f"| {_delta(s.get('p90_a'), s.get('p90_b'))} |"
    )


HEADER = (
    "| scope | n | skipped | median A | median B | median delta "
    "| p90 A | p90 B | p90 delta |\n|---|---|---|---|---|---|---|---|---|"
)


def _describe(run: dict) -> str:
    return (
        f"`{run['run_id']}`: environment={run['environment']}, "
        f"ff={run.get('ff') or 'default'}, trials={run['num_trials']}, "
        f"build={run['build']}"
    )


def _warnings(a: dict, b: dict) -> list[str]:
    notes = []
    for field in ("environment", "ff", "num_trials"):
        if a.get(field) != b.get(field):
            notes.append(
                f"{field} differs ({a.get(field)!r} against {b.get(field)!r}): "
                "the delta may measure the setup, not the change."
            )
    return notes


def build_report(a: dict, b: dict, groups: dict[str, str], metrics=ALL_METRICS) -> str:
    a_entries, b_entries = _active(a), _active(b)
    shared = sorted(set(a_entries) & set(b_entries))
    lines = [
        "# Efficiency report",
        "",
        f"- A: {_describe(a)}",
        f"- B: {_describe(b)}",
        f"- Shared cases: {len(shared)} "
        f"(only in A: {len(set(a_entries) - set(b_entries))}, "
        f"only in B: {len(set(b_entries) - set(a_entries))})",
        "- Delta is B minus A. Medians and p90 use the cases where both runs "
        "have a value. `skipped` counts the shared cases without one.",
        "- Info-only: these numbers never gate. Compare a delta with the A/A "
        "noise floor.",
    ]
    for note in _warnings(a, b):
        lines.append(f"- WARNING: {note}")
    if not shared:
        lines += ["", "No shared cases."]
        return "\n".join(lines) + "\n"

    by_group: dict[str, list[str]] = {}
    for uid in shared:
        by_group.setdefault(groups.get(uid, UNKNOWN_GROUP), []).append(uid)

    lines += ["", "## All cases", "", HEADER]
    for metric in metrics:
        lines.append(_row(metric, summarise(a_entries, b_entries, shared, metric)))

    for metric in metrics:
        lines += ["", f"## {metric} by case group", "", HEADER]
        for group in sorted(by_group):
            stats = summarise(a_entries, b_entries, by_group[group], metric)
            lines.append(_row(f"{group} ({len(by_group[group])})", stats))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_a", type=Path, help="baseline run file")
    parser.add_argument("run_b", type=Path, help="candidate run file")
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument(
        "--metric",
        action="append",
        choices=ALL_METRICS,
        help="only these metrics (repeatable); default all",
    )
    args = parser.parse_args()
    report = build_report(
        read_run(args.run_a),
        read_run(args.run_b),
        group_map(args.cases_dir),
        tuple(args.metric) if args.metric else ALL_METRICS,
    )
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
