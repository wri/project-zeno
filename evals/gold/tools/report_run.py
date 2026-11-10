"""Print a four-layer Markdown report of one ledger run.

    uv run python tools/report_run.py results/runs/<run_id>.json

The layers, in order: row verdicts; the bucket table (scores beside coverage
denominators); reconciliation (implied versus evaluated checks, each miss
listed); diagnostics (failing and errored rows, judge errors, slow rows).
Use it for a quick read in the terminal or to paste into a PR.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.buckets import (
    BUCKETS,
    INFO_ONLY,
    implied_checks_for_case,
    is_info_only,
    reconcile,
    row_verdict,
    summarize_buckets,
)
from goldset.ledger import read_run
from goldset.store import load_store


def _bucket_line(name: str, block: dict) -> str:
    dedicated, shared = block["dedicated"], block["shared"]
    if dedicated["evaluated"] == 0 and shared["evaluated"] == 0:
        score = "— UNMEASURED"
    else:
        parts = []
        if dedicated["evaluated"]:
            parts.append(f"dedicated {dedicated['passed']}/{dedicated['evaluated']}")
        else:
            parts.append("dedicated —")
        if shared["evaluated"]:
            parts.append(f"shared {shared['passed']}/{shared['evaluated']}")
        score = ", ".join(parts)
    return f"| {name} | {score} | {block['rows_covered']} |"


def render(
    run: dict,
    expected_by_uid: dict[str, dict[str, str]],
    status_by_uid: dict[str, str] | None = None,
) -> str:
    entries = run["results"]
    buckets = run.get("buckets") or summarize_buckets(entries)
    verdicts = buckets["verdicts"]

    lines = [
        f"# {run['run_id']}",
        "",
        f"{run['environment']} · build {run['build']} · ff {run['ff'] or '—'} · "
        f"{run['num_trials']} trial(s) · caseset {run['caseset_version']}",
        "",
        f"**Rows clean: {verdicts['pass']}/{buckets['rows_total']}** "
        f"(fail {verdicts['fail']}, error {verdicts['error']}, "
        f"uncovered {verdicts['uncovered']})",
    ]
    uncovered = [e["id"] for e in entries if row_verdict(e) == "uncovered"]
    if uncovered:
        lines.append(f"Uncovered rows (measured nothing): {', '.join(uncovered)}")

    lines += [
        "",
        "| bucket | checks passed/evaluated | rows covered |",
        "|---|---|---|",
    ]
    lines += [_bucket_line(bucket, buckets[bucket]) for bucket in BUCKETS]
    lines.append(
        f"\nRows total: {buckets['rows_total']}. Info-only checks "
        f"({', '.join(sorted(INFO_ONLY))}) are excluded from verdicts."
    )

    reconciliation = reconcile(entries, expected_by_uid)
    lines += [
        "",
        f"**Reconciliation:** {reconciliation['evaluated_of_implied']}"
        f"/{reconciliation['implied']} implied checks evaluated"
        + (
            f"; {reconciliation['rows_not_in_store']} rows not in current store"
            if reconciliation["rows_not_in_store"]
            else ""
        ),
    ]
    if len(reconciliation["missing"]) <= 20:
        for miss in reconciliation["missing"]:
            lines.append(f"- MISSING: {miss['id']} `{miss['check']}` never evaluated")
    else:
        by_check: dict[str, list[str]] = {}
        for miss in reconciliation["missing"]:
            by_check.setdefault(miss["check"], []).append(miss["id"])
        for check, ids in sorted(by_check.items()):
            sample = ", ".join(ids[:6]) + (
                f", +{len(ids) - 6} more" if len(ids) > 6 else ""
            )
            lines.append(
                f"- MISSING: `{check}` never evaluated on {len(ids)} rows ({sample})"
            )

    failing = [e for e in entries if row_verdict(e) == "fail"]
    if failing:
        lines += ["", "## Failing rows", ""]
        for entry in failing:
            failed = [
                n
                for n, v in entry["checks"].items()
                if v == 0.0 and not is_info_only(n)
            ]
            status = (status_by_uid or {}).get(entry.get("uid") or "", "stale_case")
            lines.append(
                f"- {entry['id']} (status: {status}): {', '.join(sorted(failed))}"
            )
            # Multi-turn rows: show which turn's query failed which checks.
            for number, turn in enumerate(entry.get("turns_detail") or [], start=1):
                turn_failed = [n for n in failed if n.startswith(f"t{number}.")]
                if turn_failed:
                    query_preview = str(turn.get("query", ""))[:60]
                    lines.append(
                        f'    - t{number} "{query_preview}" -> '
                        + ", ".join(n.split(".", 1)[1] for n in turn_failed)
                    )
    errored = [e for e in entries if row_verdict(e) == "error"]
    if errored:
        lines += [
            "",
            "## Errored rows (fix the harness/judge before reading these as agent failures)",
            "",
        ]
        for entry in errored:
            cause = entry.get("error") or f"judge errors: {entry.get('judge_errors')}"
            lines.append(f"- {entry['id']}: {cause}")
    slow = [e for e in entries if (e.get("info") or {}).get("slow")]
    if slow:
        lines += [
            "",
            "Slow rows (> threshold): "
            + ", ".join(f"{e['id']} ({e.get('latency_s')}s)" for e in slow),
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run", type=Path)
    parser.add_argument("--cases-dir", type=Path, default=Path("cases/v2"))
    args = parser.parse_args()

    run = read_run(args.run)
    store = list(load_store(args.cases_dir))
    expected_by_uid = {
        case.uid: implied_checks_for_case(case) for _p, case, _u in store
    }
    status_by_uid = {case.uid: case.status for _p, case, _u in store}
    print(render(run, expected_by_uid, status_by_uid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
