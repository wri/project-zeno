"""Per-check flakiness of a multi-trial run.

    uv run python tools/flakiness.py results/runs/<run_id>.json [--per-case]

For each check: its mean, its flake std (the population std of one case's
trial values, averaged over cases) and how many cases' trials disagreed.
The limits are 0.10 for judged and mixed checks and 0.04 for deterministic
ones. A new judged check stays info-only until it holds 0.10 over 3 trials;
a deterministic check over 0.04 points to agent or harness instability.
`--per-case` also lists every case whose trials disagreed.

A check with fewer verdicts than the run implies (judge errors, lost trials)
is flagged INSUFFICIENT DATA and never counts as within its limit: std over
a partial sample says nothing about stability.

Exits 1 if any gating check is over its limit (shown as OVER GATE) or short
of verdicts, or if the run measured nothing at all, so an empty table never
reads as all-clear.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.buckets import base_check_name, is_info_only
from goldset.ledger import read_run
from goldset.registry import EVALUATORS

JUDGED_KINDS = {"llm_judge", "mixed"}
JUDGED_CHECKS = frozenset(
    field.removesuffix("_score")
    for spec in EVALUATORS
    if spec.kind in JUDGED_KINDS
    for field in spec.score_fields
)

DETERMINISTIC_STD_GATE = 0.04
JUDGED_STD_GATE = 0.10


def trial_values(entry: dict, check: str) -> list[float | None]:
    trials = entry.get("trials")
    if not trials:
        return [entry["checks"].get(check)]
    return [t["checks"].get(check) for t in trials]


def collect(run: dict) -> tuple[dict, list[dict]]:
    """(per-check stats, per-case flap list).

    Flakiness is WITHIN-case variance across trials: the std of one case's
    trial values, averaged over cases. Pooling values across cases would
    measure the spread of the pass rate instead (a check that consistently
    fails on 3 of 90 rows is not flaky). A fixture test pins this.
    """
    per_check_means: dict[str, list[float]] = {}
    per_check_stds: dict[str, list[float]] = {}
    per_check_expected: dict[str, int] = {}
    per_check_observed: dict[str, int] = {}
    flappy_cases: list[dict] = []
    for entry in run["results"]:
        if entry.get("stale_case"):
            continue
        flapped: list[str] = []
        for check in entry.get("checks", {}):
            recorded = trial_values(entry, check)
            values = [v for v in recorded if v is not None]
            if not values:
                continue  # no verdict in any trial: not applicable to this row
            name = base_check_name(check)
            # the row measured this check, so every trial owed a verdict;
            # a shortfall (judge error, lost trial) is data loss, not calm
            per_check_expected[name] = per_check_expected.get(name, 0) + len(recorded)
            per_check_observed[name] = per_check_observed.get(name, 0) + len(values)
            per_check_means.setdefault(name, []).append(statistics.mean(values))
            per_check_stds.setdefault(name, []).append(
                statistics.pstdev(values) if len(values) > 1 else 0.0
            )
            if len(set(values)) > 1:
                flapped.append(check)
        if flapped:
            flappy_cases.append({"id": entry.get("id"), "checks": sorted(flapped)})

    stats: dict[str, dict] = {}
    for check in sorted(per_check_means):
        flake_std = statistics.mean(per_check_stds[check])
        gate = JUDGED_STD_GATE if check in JUDGED_CHECKS else DETERMINISTIC_STD_GATE
        observed = per_check_observed[check]
        expected = per_check_expected[check]
        insufficient = observed < expected
        stats[check] = {
            "n": len(per_check_means[check]),
            "mean": statistics.mean(per_check_means[check]),
            "std": flake_std,
            "flapping_cases": sum(1 for s in per_check_stds[check] if s > 0),
            "kind": "judged" if check in JUDGED_CHECKS else "deterministic",
            "info_only": is_info_only(check),
            "observed_verdicts": observed,
            "expected_verdicts": expected,
            "insufficient_data": insufficient,
            # a partial sample can look stable precisely because the flaky
            # trials are the ones that errored, so never call it clean
            "within_gate": flake_std <= gate and not insufficient,
        }
    return stats, flappy_cases


def render(run: dict, stats: dict, flappy: list[dict], per_case: bool) -> str:
    lines = [
        f"# Flakiness: {run['run_id']} ({run['num_trials']} trials)",
        "",
        "| check | kind | cases | mean | flake std | flapping | gate |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for check, row in stats.items():
        if row["insufficient_data"]:
            flag = (
                f"**INSUFFICIENT DATA** ({row['observed_verdicts']}"
                f"/{row['expected_verdicts']} verdicts)"
            )
        elif row["info_only"]:
            flag = "info-only"
        else:
            flag = "ok" if row["within_gate"] else "**OVER GATE**"
        lines.append(
            f"| {check} | {row['kind']} | {row['n']} | {row['mean']:.2f} "
            f"| ±{row['std']:.2f} | {row['flapping_cases']} | {flag} |"
        )
    over = [
        c
        for c, r in stats.items()
        if not r["within_gate"] and not r["info_only"] and not r["insufficient_data"]
    ]
    short = [
        c for c, r in stats.items() if r["insufficient_data"] and not r["info_only"]
    ]
    lines += [
        "",
        f"Checks over their std gate: {', '.join(over) if over else 'none'}. "
        f"Rows that flapped at all: {len(flappy)}.",
    ]
    if short:
        lines.append(
            f"Checks with missing verdicts (insufficient data): {', '.join(short)}."
        )
    if per_case and flappy:
        lines += ["", "## Flapping rows", ""]
        lines += [f"- {c['id']}: {', '.join(c['checks'])}" for c in flappy]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run", type=Path)
    parser.add_argument("--per-case", action="store_true")
    args = parser.parse_args()
    run = read_run(args.run)
    if run.get("num_trials", 1) < 2:
        print("warning: single-trial run — stds are vacuous\n")
    stats, flappy = collect(run)
    if not stats:
        print(
            f"nothing measured: {run['run_id']} has no non-stale row with "
            "an evaluated check — no flakiness evidence in this run"
        )
        return 1
    print(render(run, stats, flappy, args.per_case))
    blocked = [
        c for c, r in stats.items() if not r["within_gate"] and not r["info_only"]
    ]
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
