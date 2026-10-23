"""Case-set audit: depth, coverage floors and DON'T violations.

    uv run python tools/audit_cases.py                # report (exit 0)
    uv run python tools/audit_cases.py --strict       # exit 1 on violations

Encodes the authoring rules in cases/README.md (its DOs, DON'Ts and "The
audit gate" sections):

- depth: every ready, todo or done case implies at least 2 checks across at
  least 2 buckets (the `metadata` group is the one allowed judged-only
  exception)
- coverage floors: every group and every dataset id has at least 3 active
  cases
- DON'Ts: relative-date queries (allowed when only routing is asserted),
  date expectations on datasets that are not date-scoped, judged-only cases
- selectors: a `ground_truth` selector parses and is spelled canonically
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.buckets import buckets_for, implied_checks_for_case
from goldset.groundtruth.selector import SelectorError, parse_selector
from goldset.store import Case, load_store
from goldset.templates import validate_templates

COVERAGE_FLOOR = 3
EXEMPT_GROUPS = {"metadata"}  # sanctioned judged-only capability
EXCLUDED_STATUSES = {"not doing"}

# Alert/imagery datasets take genuinely date-scoped pulls; everything else
# is annual/fixed and must not carry date expectations (cases/README.md).
DATE_SCOPED_DATASET_IDS = {"0", "11"}
DATE_SCOPED_GROUPS = {"imagery"}

RELATIVE_DATE_RE = re.compile(
    r"\b(last|past|recent|latest|this (year|month|week))\b", re.IGNORECASE
)

# The rule (cases/README.md, DON'T #1): relative-date phrasing is tolerated
# only when the case asserts *routing alone*: which AOI/dataset/layer/
# parameters the agent selected, its scope, and whether it asked to clarify.
# Those stay true whatever the calendar says. Every other expectation
# (answers, dates, class values, chart/dashboard/nudge content, judged text,
# and any key added in the future) is presumed to drift with time or data
# versions and flags. Allow-list rather than deny-list so that new
# expectation vocabulary fails safe.
ROUTING_ONLY_FIELDS = {
    "aoi_ids",
    "aoi_source",
    "dataset_id",
    "dataset_name",
    "dataset_parameters",
    "context_layer",
    "scope",
    "clarification",
}

DETERMINISTIC_FIELDS = {
    "aoi_ids",
    "dataset_id",
    "dataset_parameters",
    "context_layer",
    "start_date",
    "end_date",
    "suggested_datasets",
    "nudge_type",
    "nudge_options",
    "dashboard_created",
    "dashboard_widgets",
    "scope",
    "chart_type",
    "class_values",
    "clarification",
    # ground_truth is the most deterministic expectation in the set: the figure
    # is fetched at run time and compared in code, never judged. Deliberately
    # NOT in ROUTING_ONLY_FIELDS above — a fetch still needs a fixed window, so
    # "deforestation last year" plus a selector must keep flagging.
    "ground_truth",
}


def _queries(case: Case) -> list[str]:
    if case.is_multiturn:
        return [turn["query"] for turn in case.turns]
    return [case.query]


def _expected_maps(case: Case) -> list[dict[str, str]]:
    if case.is_multiturn:
        return [turn.get("expected") or {} for turn in case.turns]
    return [case.expected]


def _dataset_alternatives(case: Case) -> set[str]:
    ids: set[str] = set()
    for expected in _expected_maps(case):
        for alt in str(expected.get("dataset_id", "")).split(";"):
            if alt.strip():
                ids.add(alt.strip())
    return ids


def depth_violation(case: Case) -> str | None:
    if case.group in EXEMPT_GROUPS:
        return None
    implied = implied_checks_for_case(case)
    buckets = {b for check in implied for b in buckets_for(check)}
    if len(implied) >= 2 and len(buckets) >= 2:
        return None
    return (
        f"{case.id}: implies {len(implied)} check(s) in {len(buckets)} "
        f"bucket(s) — needs >=2 in >=2"
    )


def _turn_deltas(case: Case) -> list[dict]:
    if case.is_multiturn:
        return [turn.get("deltas") or {} for turn in case.turns]
    return [{}]


_TEMPLATE_TOKEN_RE = re.compile(r"\{[a-z_]+\}")


def dont_violations(case: Case) -> list[str]:
    problems = []
    for query, expected, deltas in zip(
        _queries(case), _expected_maps(case), _turn_deltas(case)
    ):
        for problem in validate_templates(query):
            problems.append(f"{case.id}: {problem}")
        query_sans_templates = _TEMPLATE_TOKEN_RE.sub("", query)
        match = RELATIVE_DATE_RE.search(query_sans_templates)
        if match:
            drifting = sorted(
                key
                for key, value in expected.items()
                if str(value).strip() and key not in ROUTING_ONLY_FIELDS
            )
            if drifting:
                problems.append(
                    f"{case.id}: relative-date phrasing ({match.group(0)!r}) "
                    f"with non-routing expectation(s) {drifting}"
                )
        has_dates = expected.get("start_date") or expected.get("end_date")
        if has_dates and case.group not in DATE_SCOPED_GROUPS:
            alternatives = {
                a.strip()
                for a in str(expected.get("dataset_id", "")).split(";")
                if a.strip()
            }
            # Every alternative must be date-scoped: "4;11" may resolve to
            # the annual dataset 4, so a mixed list is as unsafe as a bare 4.
            if alternatives and not alternatives <= DATE_SCOPED_DATASET_IDS:
                problems.append(
                    f"{case.id}: date expectations on non-date-scoped "
                    f"dataset(s) {sorted(alternatives)}"
                )
        judged_only = (
            (expected.get("answer") or expected.get("text"))
            and not (set(expected) & DETERMINISTIC_FIELDS)
            and not deltas  # a turn asserting state deltas is deterministic
        )
        if judged_only and case.group not in EXEMPT_GROUPS:
            problems.append(f"{case.id}: judged-only expectations")
    return problems


def selector_violations(case: Case) -> list[str]:
    """A ``ground_truth`` selector must parse, and must be spelled canonically.

    Two reasons, both about finding the problem early. A selector that does not
    parse aborts a run during prefetch, which is a slow way to learn about a
    typo. And the uid hashes the selector exactly as the file carries it, so two
    spellings of one selector are two versions of the same test —
    ``canonical()`` re-spells it for the ledger but cannot undo that.
    """
    problems = []
    for expected in _expected_maps(case):
        raw = str(expected.get("ground_truth") or "").strip()
        if not raw:
            continue
        try:
            canonical = parse_selector(raw).canonical()
        except SelectorError as exc:
            problems.append(f"{case.id}: {exc}")
            continue
        if raw != canonical:
            problems.append(
                f"{case.id}: ground_truth {raw!r} is not spelled canonically; "
                f"use {canonical!r}"
            )
    return problems


def audit(cases: list[Case]) -> dict:
    active = [c for c in cases if c.status.lower() not in EXCLUDED_STATUSES]
    group_counts = Counter(c.group for c in active)
    dataset_counts: Counter = Counter()
    for case in active:
        for dataset_id in _dataset_alternatives(case):
            dataset_counts[dataset_id] += 1

    return {
        "active": len(active),
        "parked": len(cases) - len(active),
        "depth": [v for c in active if (v := depth_violation(c))],
        "donts": [p for c in active for p in dont_violations(c)],
        "selectors": [p for c in active for p in selector_violations(c)],
        "thin_groups": {
            g: n for g, n in sorted(group_counts.items()) if n < COVERAGE_FLOOR
        },
        "thin_datasets": {
            d: n for d, n in sorted(dataset_counts.items()) if n < COVERAGE_FLOOR
        },
    }


def _section(items: list[str]) -> list[str]:
    return items or ["- none"]


def render(report: dict) -> str:
    lines = [
        "# Case-set audit",
        "",
        f"Active cases: {report['active']} (+{report['parked']} parked)",
        "",
        f"## Depth violations ({len(report['depth'])})",
        *_section([f"- {v}" for v in report["depth"]]),
        "",
        f"## DON'T violations ({len(report['donts'])})",
        *_section([f"- {v}" for v in report["donts"]]),
        "",
        f"## Selector violations ({len(report['selectors'])})",
        *_section([f"- {v}" for v in report["selectors"]]),
        "",
        f"## Groups below the floor of {COVERAGE_FLOOR}",
        *_section([f"- {g}: {n}" for g, n in report["thin_groups"].items()]),
        "",
        f"## Datasets below the floor of {COVERAGE_FLOOR}",
        *_section([f"- id {d}: {n}" for d, n in report["thin_datasets"].items()]),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cases-dir", type=Path, default=Path("cases/v2"))
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on depth, DON'T or selector violations (CI "
        "runs this). Coverage floors stay report-only: "
        "clearing them means authoring new cases, not fixing "
        "existing ones.",
    )
    args = parser.parse_args(argv)

    cases = [case for _p, case, _u in load_store(args.cases_dir)]
    report = audit(cases)
    print(render(report))
    if args.strict and (report["depth"] or report["donts"] or report["selectors"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
