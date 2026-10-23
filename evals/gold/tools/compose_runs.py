"""Combine a primary run with scoped re-runs into one current picture.

    uv run python tools/compose_runs.py results/runs/PRIMARY.json
        results/runs/SUPP1.json [results/runs/SUPP2.json ...] [--json out.json]

This never writes to `results/runs/`. Run files are immutable, and a run's
metadata (`ff`, `workers`, `build`) must describe how its own rows were
produced, so rows from another run cannot be spliced in. See "Composing a
current picture across runs" in results/README.md.

So the combining happens in the analysis, not in the record. Each active case
is resolved to its latest measurement at its current uid: supplementary runs
override the primary, and each supplementary run overrides those listed
before it. Every row is reported with the run it came from, and active cases
that no run measured are listed rather than dropped.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from goldset.buckets import is_info_only, row_verdict, summarize_buckets  # noqa: E402
from goldset.store import load_store  # noqa: E402


def load_run(path: Path) -> dict:
    run = json.loads(path.read_text())
    run["_path"] = str(path)
    return run


def compose(primary: dict, supplements: list[dict], cases_dir: Path) -> dict:
    """Resolve every active case to its freshest measurement at its current uid."""
    active = {
        case.uid: case
        for _, case, _ in load_store(cases_dir)
        if (case.status or "").strip().lower() != "not doing"
    }

    # Later sources win, so walk primary first and let supplements overwrite.
    resolved: dict[str, tuple[dict, dict]] = {}
    for run in [primary, *supplements]:
        for entry in run["results"]:
            uid = entry.get("uid")
            if uid in active:
                resolved[uid] = (entry, run)

    rows, provenance, unmeasured = [], Counter(), []
    for uid, case in sorted(active.items(), key=lambda kv: kv[1].id):
        found = resolved.get(uid)
        if found is None:
            unmeasured.append(case.id)
            continue
        entry, run = found
        rows.append(entry)
        provenance[run["run_id"]] += 1

    verdicts = Counter(row_verdict(entry) for entry in rows)
    return {
        "sources": [
            {
                "run_id": run["run_id"],
                "ff": run.get("ff"),
                "num_trials": run.get("num_trials"),
                "workers": run.get("workers"),
                "build": run.get("build"),
                "caseset_version": run.get("caseset_version"),
                "rows_used": provenance[run["run_id"]],
            }
            for run in [primary, *supplements]
        ],
        "active_cases": len(active),
        "measured": len(rows),
        "unmeasured": unmeasured,
        "verdicts": dict(verdicts),
        "buckets": summarize_buckets(rows),
        "every_trial_clean": sum(1 for entry in rows if _all_trials_clean(entry)),
        "rows": [
            {
                "id": entry["id"],
                "uid": entry["uid"],
                "verdict": row_verdict(entry),
                "source": run["run_id"],
            }
            for entry, run in (
                resolved[uid] for uid in sorted(resolved, key=lambda u: active[u].id)
            )
        ],
    }


def _all_trials_clean(entry: dict) -> bool:
    if entry.get("error") or entry.get("judge_errors"):
        return False
    trials = entry.get("trials") or [{"checks": entry.get("checks", {})}]
    return all(
        all(
            value != 0.0
            for name, value in (trial.get("checks") or {}).items()
            if value is not None and not is_info_only(name)
        )
        for trial in trials
    )


def render(report: dict) -> str:
    lines = ["# Composed result (analysis only — not a ledger entry)", ""]
    lines.append("| source run | ff | trials | rows used |")
    lines.append("|---|---|---:|---:|")
    for source in report["sources"]:
        lines.append(
            f"| `{source['run_id']}` | {source['ff'] or '**unset**'} | "
            f"{source['num_trials']} | {source['rows_used']} |"
        )
    ff_values = {source["ff"] for source in report["sources"]}
    if len(ff_values) > 1:
        lines += [
            "",
            f"> ⚠ **Sources disagree on `ff`** ({', '.join(str(f) for f in sorted(ff_values, key=str))}). "
            "Different `ff` values expose different agent tools, so rows from "
            "runs with differing `ff` must never be composed: re-run the "
            "supplements with the primary's `ff`.",
        ]

    total = report["measured"]
    verdicts = report["verdicts"]
    passed = verdicts.get("pass", 0)
    lines += [
        "",
        f"**{passed}/{total} pass = {passed / total:.0%}**" if total else "no rows",
        "",
        f"- verdicts: {verdicts}",
        f"- clean on every trial: {report['every_trial_clean']}/{total}"
        + (f" = {report['every_trial_clean'] / total:.0%}" if total else ""),
        f"- active cases: {report['active_cases']}, measured: {total}",
    ]
    if report["unmeasured"]:
        lines.append(
            f"- **unmeasured at their current uid ({len(report['unmeasured'])}): "
            f"{', '.join(report['unmeasured'])}**"
        )
    failing = [row for row in report["rows"] if row["verdict"] != "pass"]
    if failing:
        lines += ["", "## Not passing", ""]
        for row in failing:
            lines.append(f"- {row['id']} — {row['verdict']} (from `{row['source']}`)")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("primary", type=Path)
    parser.add_argument("supplements", type=Path, nargs="*")
    parser.add_argument("--cases-dir", type=Path, default=Path("cases/v2"))
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    report = compose(
        load_run(args.primary),
        [load_run(path) for path in args.supplements],
        args.cases_dir,
    )
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
