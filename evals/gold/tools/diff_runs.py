"""Regression diff between two ledger runs.

    uv run python tools/diff_runs.py results/runs/A.json results/runs/B.json
        [--json out.json] [--strict] [--fail-on-regression] [--fail-on-coverage-loss]

Only diff runs with the same `ff`, the same trial count (3) and the same
environment; otherwise trial-to-trial noise, or a change in the agent's
tools, counts as regressions. See "Comparing two runs" in results/README.md.

The diff covers only the uids present in both runs (rows flagged
`stale_case` are left out), so cases added, removed or edited between the
runs are reported as identity churn, never as regressions. For each check,
from run A (older) to run B (newer):

    regression        1.0 -> 0.0
    recovery          0.0 -> 1.0
    data bump         a ground-truth check flipped either way while the digest
                      of the values it was graded against moved
    coverage gained   not evaluated -> evaluated
    coverage lost     evaluated -> not evaluated

A data bump tells a dataset update served by the analytics API apart from
an agent regression. The API exposes no dataset version, so the digest
recorded on each ground-truth entry is the only signal. Each bump names its
cause: `data` (same request, different numbers), `request` (GOLD's own
request changed, so a harness change) or `fixed_dataset` (a dataset declared
never to change has changed). Bumps are listed, never counted as regressions
or recoveries, and never gate.

A bump can hide a real break. An agent that fails in the same run the data
moves is filed here, and if it stays broken the next diff sees 0.0 -> 0.0.
So a `ground_truth_match` bump is checked against the agent's own recorded
figure: one that matches neither run's values, or no figure at all, is not
explained by the data and is flagged `possible_hidden_regression`. Flagged
bumps are reported, not gated.

Info-only checks (`goldset.buckets.INFO_ONLY`, also under a multi-turn
`t<N>.` prefix) are reported but never gate. The headline splits regressions
and lost checks into gating and info-only counts, and the `--fail-on-*` gates
read the gating counts.

`--strict` refuses (exit 2) to compare runs whose caseset_version differs.
`--fail-on-regression` exits 1 on any gating regression: this is the release
gate.
`--fail-on-coverage-loss` exits 1 if any gating check went from evaluated to
not evaluated. It is off by default; turn it on to catch a harness bug that
silently stops scoring a check, which would otherwise pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.buckets import BUCKETS, buckets_for, is_info_only
from goldset.ledger import read_run

TRANSITIONS = (
    "regressions",
    "recoveries",
    "data_bumps",
    "coverage_gained",
    "coverage_lost",
)

# Checks graded against values fetched at run start: the only ones a data
# change can explain. A flip on aoi_id_match in the same row stays a regression.
# Named here rather than imported, so this tool never loads the judge module.
GROUND_TRUTH_CHECKS = frozenset({"ground_truth_match", "ground_truth_answer"})

CAUSE_WORDS = {
    "data": "data changed",
    "request": "GOLD's request changed",
    "fixed_dataset": "fixed dataset moved",
}


def indexable(run: dict) -> dict[str, dict]:
    return {
        entry["uid"]: entry
        for entry in run["results"]
        if entry.get("uid") and not entry.get("stale_case")
    }


def classify(prev: float | None, cur: float | None) -> str | None:
    if prev == 1.0 and cur == 0.0:
        return "regressions"
    if prev == 0.0 and cur == 1.0:
        return "recoveries"
    if prev is None and cur is not None:
        return "coverage_gained"
    if prev is not None and cur is None:
        return "coverage_lost"
    return None


def gating_count(items: list[dict]) -> int:
    return sum(1 for item in items if not item["info_only"])


def data_bump_cause(entry_a: dict, entry_b: dict) -> str | None:
    """Why the digest moved between two runs of one case, or None if it didn't.

    None too when either side has no digest (an unresolved selector, or a run
    from before digests were recorded): without both, nothing can be told apart.
    """
    gt_a = entry_a.get("ground_truth") or {}
    gt_b = entry_b.get("ground_truth") or {}
    if (
        not gt_a.get("digest")
        or not gt_b.get("digest")
        or gt_a["digest"] == gt_b["digest"]
    ):
        return None
    # Same uid means the same case, so a different request can only come from
    # GOLD's request builder — not from the case and not from the data.
    if gt_a.get("request") != gt_b.get("request"):
        return "request"
    if gt_b.get("content_date_fixed"):
        return "fixed_dataset"
    return "data"


def _close(figure: float, value: float, tolerance: float) -> bool:
    if value == 0:
        return figure == 0
    return abs(figure - value) / abs(value) <= tolerance


def hidden_regression(
    entry_a: dict, entry_b: dict, tolerance: float | None
) -> str | None:
    """Why a 1.0 -> 0.0 ground_truth_match bump may be a real break, or None.

    A healthy agent either tracks the new values or still reads the previous
    ones (a stale read on its side). A figure matching neither, or no figure,
    is not explained by the data. Only B's failing trials are examined, and it
    stays silent when the evidence was not recorded.
    """
    gt_a, gt_b = entry_a["ground_truth"], entry_b["ground_truth"]
    agent_values = gt_b.get("agent_values")
    if tolerance is None or not agent_values:
        return None
    before, now = gt_a.get("values") or [], gt_b.get("values") or []
    trials = [trial["checks"] for trial in entry_b.get("trials") or [entry_b]]
    for checks, figures in zip(trials, agent_values):
        if checks.get("ground_truth_match") != 0.0 or figures is None:
            continue
        for index, figure in enumerate(figures):
            if index >= len(before) or index >= len(now):
                continue
            if figure is None:
                return "the agent's pull held no figure for the metric"
            if not (
                _close(figure, now[index], tolerance)
                or _close(figure, before[index], tolerance)
            ):
                return (
                    f"the agent's pull gave {figure:,.2f}, matching neither run's "
                    f"data ({before[index]:,.2f} before, {now[index]:,.2f} now)"
                )
    return None


def diff(run_a: dict, run_b: dict) -> dict:
    index_a, index_b = indexable(run_a), indexable(run_b)
    shared = sorted(set(index_a) & set(index_b))
    tolerance = (run_b.get("ground_truth") or {}).get("tolerance")
    result: dict = {name: [] for name in TRANSITIONS}
    for uid in shared:
        entry_a, entry_b = index_a[uid], index_b[uid]
        for check in sorted(set(entry_a["checks"]) | set(entry_b["checks"])):
            prev, cur = entry_a["checks"].get(check), entry_b["checks"].get(check)
            kind = classify(prev, cur)
            if kind:
                # is_info_only strips the multi-turn ``t<N>.`` prefix; a bare
                # INFO_ONLY lookup let t2.charts_answer_judge gate the release.
                item = {
                    "uid": uid,
                    "id": entry_b.get("id") or entry_a.get("id"),
                    "check": check,
                    "buckets": list(buckets_for(check)),
                    "info_only": is_info_only(check),
                }
                if (
                    kind in ("regressions", "recoveries")
                    and check in GROUND_TRUTH_CHECKS
                ):
                    cause = data_bump_cause(entry_a, entry_b)
                    if cause:
                        item.update(
                            direction=f"{prev} → {cur}",
                            cause=cause,
                            digests=[
                                entry_a["ground_truth"]["digest"],
                                entry_b["ground_truth"]["digest"],
                            ],
                        )
                        if kind == "regressions" and check == "ground_truth_match":
                            suspect = hidden_regression(entry_a, entry_b, tolerance)
                            if suspect:
                                item["possible_hidden_regression"] = suspect
                        kind = "data_bumps"
                if kind in ("regressions", "data_bumps"):
                    reason = (entry_b.get("reasons") or {}).get(check)
                    if reason:
                        item["reason"] = reason
                result[kind].append(item)
    result["regressions_by_bucket"] = {
        bucket: sum(
            1
            for item in result["regressions"]
            if bucket in item["buckets"] and not item["info_only"]
        )
        for bucket in BUCKETS
    }
    # Additive fields: the per-item lists above keep their shape, and these
    # counts are the ones the --fail-on-* gates read.
    result["gating_regressions"] = gating_count(result["regressions"])
    result["gating_coverage_lost"] = gating_count(result["coverage_lost"])
    result["shared_cases"] = len(shared)
    result["only_in_a"] = len(set(index_a) - set(index_b))
    result["only_in_b"] = len(set(index_b) - set(index_a))
    result["stale_a"] = sum(1 for e in run_a["results"] if e.get("stale_case"))
    result["stale_b"] = sum(1 for e in run_b["results"] if e.get("stale_case"))
    return result


def split_count(items: list[dict], label: str) -> str:
    """``3 regressions (2 gating, 1 info-only)``: the total alone overstates
    what the gate acts on, since info-only transitions never fail it."""
    gating = gating_count(items)
    return f"{len(items)} {label} ({gating} gating, {len(items) - gating} info-only)"


def render(run_a: dict, run_b: dict, report: dict) -> str:
    lines = [
        f"# {run_a['run_id']}  →  {run_b['run_id']}",
        "",
        f"Shared cases: {report['shared_cases']} "
        f"(identity churn: {report['only_in_a']} only in A, "
        f"{report['only_in_b']} only in B; "
        f"stale: {report['stale_a']}/{report['stale_b']})",
        "",
        f"**{split_count(report['regressions'], 'regressions')}, "
        f"{len(report['recoveries'])} recoveries, "
        f"{len(report['data_bumps'])} data bumps, "
        f"{len(report['coverage_gained'])} checks gained, "
        f"{split_count(report['coverage_lost'], 'checks lost')}**",
    ]
    by_bucket = report.get("regressions_by_bucket") or {}
    if any(by_bucket.values()):
        lines.append(
            "Regressions by bucket: "
            + ", ".join(f"{b} {n}" for b, n in by_bucket.items() if n)
        )
    for kind, marker in (("regressions", "✗"), ("recoveries", "✓")):
        if report[kind]:
            lines += ["", f"## {kind}", ""]
            for item in report[kind]:
                line = f"- {marker} {item['id']} ({item['uid']}) `{item['check']}`"
                if item.get("reason"):
                    line += f" — {item['reason'][:160]}"
                lines.append(line)
    if report["data_bumps"]:
        flagged = sum(
            1 for i in report["data_bumps"] if i.get("possible_hidden_regression")
        )
        lines += ["", "## data bumps", ""]
        if flagged:
            lines += [
                f"**{flagged} flagged as a possible hidden regression** — "
                "review before trusting the regression count.",
                "",
            ]
        for item in report["data_bumps"]:
            before, after = item["digests"]
            line = (
                f"- ↕ {item['id']} ({item['uid']}) `{item['check']}` "
                f"{item['direction']} · {CAUSE_WORDS[item['cause']]} · "
                f"digest {before[:8]} → {after[:8]}"
            )
            if item.get("reason"):
                line += f" — {item['reason'][:160]}"
            lines.append(line)
            if item.get("possible_hidden_regression"):
                lines.append(
                    f"  - ⚠ possible hidden regression: "
                    f"{item['possible_hidden_regression']}"
                )
    for kind in ("coverage_gained", "coverage_lost"):
        if report[kind]:
            lines += ["", f"## {kind.replace('_', ' ')}", ""]
            lines += [f"- {i['id']} `{i['check']}`" for i in report[kind]]
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_a", type=Path, help="older run JSON")
    parser.add_argument("run_b", type=Path, help="newer run JSON")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--fail-on-coverage-loss", action="store_true")
    args = parser.parse_args()

    run_a, run_b = read_run(args.run_a), read_run(args.run_b)
    if run_a["caseset_version"] != run_b["caseset_version"]:
        message = (
            f"caseset_version differs: {run_a['caseset_version']} vs "
            f"{run_b['caseset_version']} — comparing uid intersection only"
        )
        if args.strict:
            print(f"refused (--strict): {message}")
            return 2
        print(f"note: {message}\n")

    report = diff(run_a, run_b)
    print(render(run_a, run_b, report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if args.fail_on_regression and report["gating_regressions"]:
        return 1
    if args.fail_on_coverage_loss and report["gating_coverage_lost"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
