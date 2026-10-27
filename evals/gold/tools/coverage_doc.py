"""Generate the case-set coverage document (COVERAGE.md).

Like MANIFEST.json, the output is derived from the case store and never
hand-edited: it outlines what the set contains (groups, statuses, fields,
multi-turn shapes) and what it covers (which buckets the active cases'
implied checks reach), plus the gaps. Regenerate after any case edit:

    uv run python tools/coverage_doc.py                # writes cases/v2/COVERAGE.md
    uv run python tools/coverage_doc.py --check        # CI freshness gate

Coverage counts use gating checks only; info-only checks are reported
separately because they never enter a verdict.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sync_zeno_catalog import INSTRUCTION_FIELDS

from goldset.buckets import (
    BUCKETS,
    DEDICATED,
    INFO_ONLY,
    SHARED,
    base_check_name,
    implied_checks_for_case,
)
from goldset.store import load_store, read_manifest

ACTIVE_EXCLUDED = {"not doing"}

# Expected field -> the checks it switches on, for the census table. Keep in
# step with buckets.implied_checks, the authoritative map; "(+ ... when ...)"
# marks a conditional check, which may abstain and so is never implied.
FIELD_CHECKS = {
    "aoi_ids": "aoi_id_match",
    "dataset_id": "dataset_id_match",
    "dataset_parameters": "dataset_parameter_match",
    "context_layer": "context_layer_match",
    "start_date": "date_extraction (with end_date)",
    "end_date": "date_extraction (with start_date)",
    "answer": (
        "agent_answer, chart_produced, data_pull_exists, "
        "answered_without_data (+ charts_answer when a chart exists)"
    ),
    "ground_truth": "ground_truth_match, ground_truth_answer (info-only)",
    "text": "expected_text_match",
    "clarification": "clarification_requested",
    "suggested_datasets": (
        "suggested_datasets_match (legacy: the agent now "
        "writes nudge; author nudge_type / nudge_options)"
    ),
    "nudge_type": "nudge_match",
    "nudge_options": "nudge_match",
    "dashboard_created": "dashboard_created",
    "dashboard_widgets": (
        "dashboard_widgets_match (+ dashboard_widgets_valid " "when a dashboard exists)"
    ),
    "class_values": "class_value_match (info-only)",
    "chart_type": "chart_type_match",
    "scope": "scope_match",
    "aoi_source": "no check of its own (dashboard_aoi_match also compares it)",
    "dataset_name": "reference only",
}


def case_expected_fields(case) -> set[str]:
    if case.is_multiturn:
        fields: set[str] = set()
        for turn in case.turns:
            fields |= {k for k, v in (turn.get("expected") or {}).items() if v}
        return fields
    return {k for k, v in case.expected.items() if v}


def expected_records(case) -> list[dict]:
    """One expectation mapping per turn (single-turn cases have one)."""
    if case.is_multiturn:
        return [turn.get("expected") or {} for turn in case.turns]
    return [case.expected]


def split_dataset_ids(value: object) -> set[str]:
    """Expected dataset_id values accept alternatives: '8;10' means either."""
    return {part.strip() for part in str(value or "").split(";") if part.strip()}


def expected_parameter_names(expected: dict, case_id: str) -> set[str]:
    raw = str(expected.get("dataset_parameters") or "").strip()
    if not raw:
        return set()
    try:
        return {entry["name"] for entry in json.loads(raw)}
    except (ValueError, TypeError, KeyError) as exc:
        raise SystemExit(f"{case_id}: unparseable dataset_parameters: {exc}")


# Expectations that make a case grade the *content* of an answer, and so
# exercise a dataset's prompt/code/presentation instructions. `ground_truth`
# counts: it asserts the same kind of figure as `answer`, fetched at run time
# instead of stored in the case.
ANSWER_GRADED_FIELDS = ("answer", "text", "ground_truth")


def dataset_stats(cases) -> dict[str, dict]:
    """Per expected dataset id: case count, answer-graded case count, and the
    context layers / parameter names those cases exercise. Pairing is per
    turn, so a multi-turn case only credits the dataset each turn sets, and
    each case counts a given dataset at most once."""
    stats: dict[str, dict] = {}
    for case in cases:
        ids: set[str] = set()
        answered: set[str] = set()
        layers: set[tuple[str, str]] = set()
        params: set[tuple[str, str]] = set()
        for record in expected_records(case):
            rec_ids = split_dataset_ids(record.get("dataset_id"))
            ids |= rec_ids
            if any(str(record.get(f) or "").strip() for f in ANSWER_GRADED_FIELDS):
                answered |= rec_ids
            layer = str(record.get("context_layer") or "").strip()
            layers |= {(i, layer) for i in rec_ids if layer}
            names = expected_parameter_names(record, case.id)
            params |= {(i, n) for i in rec_ids for n in names}
        for ds_id in ids:
            entry = stats.setdefault(
                ds_id,
                {
                    "cases": 0,
                    "answered": 0,
                    "layers": Counter(),
                    "params": Counter(),
                },
            )
            entry["cases"] += 1
            entry["answered"] += ds_id in answered
        for ds_id, layer in layers:
            stats[ds_id]["layers"][layer] += 1
        for ds_id, name in params:
            stats[ds_id]["params"][name] += 1
    return stats


def render_dataset_section(catalog: dict | None, active) -> tuple[list[str], list[str]]:
    """Dataset-coverage section lines, plus its bullets for Known gaps."""
    lines = ["", "## Dataset coverage (project-zeno catalog)", ""]
    if catalog is None:
        lines += [
            "No catalog snapshot found: run `uv run python "
            "tools/sync_zeno_catalog.py` to snapshot project-zeno's dataset",
            "catalog, then regenerate this doc.",
        ]
        return lines, [
            "- Dataset coverage unmeasured: no `zeno_catalog.json` snapshot; "
            "run `tools/sync_zeno_catalog.py`.",
        ]
    source = catalog["source"]
    datasets = catalog["datasets"]
    stats = dataset_stats(active)
    lines += [
        f"Catalog snapshot `cases/zeno_catalog.json`: "
        f"project-zeno@{source['sha'][:7]} ({source['ref']}, synced "
        f"{source['synced']}), {len(datasets)} datasets. Refresh with",
        "`uv run python tools/sync_zeno_catalog.py`, then regenerate this doc.",
        "A case counts toward every dataset its `dataset_id` accepts (`8;10`",
        "counts toward both 8 and 10).",
        "",
        "Each dataset carries four instruction fields that steer the agent:",
        "`selection_hints` (when to pick the dataset), `prompt_instructions`,",
        "`code_instructions` and `presentation_instructions`. A dataset missing",
        "any of them shows `(missing: …)` after its name. Any case that grades",
        "`dataset_id` exercises `selection_hints`; only answer-graded cases",
        "(those expecting `answer`, `text` or `ground_truth`, counted in the",
        "answer-graded column) exercise the other three.",
        "",
        "| id | dataset | cases | answer-graded | parameters covered "
        "| context layers covered |",
        "|---|---|---|---|---|---|",
    ]
    no_cases: list[str] = []
    param_gaps: dict[str, list[str]] = {}
    layer_gaps: dict[str, list[str]] = {}
    for ds in datasets:
        ds_id = ds["dataset_id"]
        st = stats.get(
            ds_id, {"cases": 0, "answered": 0, "layers": Counter(), "params": Counter()}
        )
        missing = [f for f in INSTRUCTION_FIELDS if f not in ds.get("instructions", [])]
        name = ds["dataset_name"] + (
            f" (missing: {', '.join(sorted(missing))})" if missing else ""
        )
        if st["cases"] == 0:
            no_cases.append(ds_id)
        param_cells = []
        for param in ds["parameters"]:
            count = st["params"].get(param["name"], 0)
            if count == 0:
                param_gaps.setdefault(param["name"], []).append(ds_id)
            param_cells.append(
                f"{param['name']} ×{count}" + (" ← gap" if count == 0 else "")
            )
        layer_cells = []
        for layer in ds["context_layers"]:
            count = st["layers"].get(layer, 0)
            if count == 0:
                layer_gaps.setdefault(layer, []).append(ds_id)
            layer_cells.append(f"{layer} ×{count}" + (" ← gap" if count == 0 else ""))
        cases_cell = str(st["cases"]) + (" ← gap" if st["cases"] == 0 else "")
        lines.append(
            f"| {ds_id} | {name} | {cases_cell} | {st['answered']} "
            f"| {', '.join(param_cells) or '—'} "
            f"| {', '.join(layer_cells) or '—'} |"
        )
    unknown = sorted(set(stats) - {d["dataset_id"] for d in datasets})
    if unknown:
        details = ", ".join(
            f"{u} ({stats[u]['cases']} case{'s' if stats[u]['cases'] != 1 else ''})"
            for u in unknown
        )
        lines += [
            "",
            f"Expected `dataset_id` values not in the catalog: {details}; "
            "fix the cases or refresh the snapshot.",
        ]
    bullets = []
    if no_cases:
        bullets.append(
            f"- Catalog datasets with no active case: {', '.join(no_cases)}."
        )
    features = []
    if param_gaps:
        features.append(
            "parameters: "
            + ", ".join(
                f"{name} ({', '.join(ids)})" for name, ids in param_gaps.items()
            )
        )
    if layer_gaps:
        features.append(
            "context layers: "
            + ", ".join(
                f"{layer} ({', '.join(ids)})" for layer, ids in layer_gaps.items()
            )
        )
    if features:
        bullets.append(
            "- Catalog features no active case exercises — " + "; ".join(features) + "."
        )
    return lines, bullets


def bucket_case_coverage(cases) -> dict[str, dict[str, int]]:
    """Per bucket: active cases reached via a dedicated gating check, and
    cases reached via shared gating checks only."""
    out = {b: {"dedicated": 0, "shared_only": 0} for b in BUCKETS}
    for case in cases:
        implied = {base_check_name(c) for c in implied_checks_for_case(case)}
        implied -= INFO_ONLY
        for bucket in BUCKETS:
            dedicated = any(DEDICATED.get(c) == bucket for c in implied)
            shared = any(bucket in SHARED.get(c, ()) for c in implied)
            if dedicated:
                out[bucket]["dedicated"] += 1
            elif shared:
                out[bucket]["shared_only"] += 1
    return out


def render(cases_dir: Path, catalog_path: Path | None = None) -> str:
    manifest = read_manifest(cases_dir)
    if manifest is None:
        raise SystemExit(f"no manifest under {cases_dir}: run tools/check.py --fix")
    catalog_path = catalog_path or (cases_dir.parent / "zeno_catalog.json")
    catalog = (
        json.loads(catalog_path.read_text(encoding="utf-8"))
        if catalog_path.exists()
        else None
    )
    cases = [case for _path, case, _uid in load_store(cases_dir)]
    active = [c for c in cases if c.status.lower() not in ACTIVE_EXCLUDED]

    statuses = Counter(c.status.lower() for c in cases)
    lines = [
        f"# GOLD case-set coverage: {cases_dir.name}",
        "",
        "Generated by `tools/coverage_doc.py` from the case store; never",
        "hand-edited. Regenerate after any case edit; CI fails a PR whose copy",
        "is stale (`--check`). Coverage counts use **gating** checks only;",
        "info-only checks are listed separately (they never enter a verdict).",
        "Terms are defined in the [README glossary](../../README.md#glossary).",
        "",
        f"`caseset_version {manifest['caseset_version']}` · {len(cases)} cases · "
        + " · ".join(f"{s} {n}" for s, n in sorted(statuses.items()))
        + f" · **{len(active)} active** (everything but `not doing` runs by default)",
        "",
        f"_Last updated: {date.today().isoformat()}_",
        "",
        "## Groups",
        "",
        "| group | cases | active | statuses |",
        "|---|---|---|---|",
    ]
    by_group: dict[str, list] = {}
    for case in cases:
        by_group.setdefault(case.group, []).append(case)
    for group in sorted(by_group):
        members = by_group[group]
        live = [c for c in members if c.status.lower() not in ACTIVE_EXCLUDED]
        st = Counter(c.status.lower() for c in members)
        st_text = ", ".join(f"{k} {v}" for k, v in sorted(st.items()))
        lines.append(f"| {group} | {len(members)} | {len(live)} | {st_text} |")

    lines += [
        "",
        "## Bucket coverage (active cases)",
        "",
        "For each bucket, the number of active cases whose expected values",
        "imply at least one gating check in it. An implied check must evaluate",
        "on every run, so this count is a floor, not a best case. A *dedicated*",
        "check belongs to one bucket; a *shared* check ("
        + ", ".join(f"`{name}`" for name in SHARED)
        + ") spans two,",
        'so its failure cannot be pinned on either. "Via shared only" counts',
        "cases that reach a bucket through shared checks alone. Conditional",
        "checks (such as `charts_answer`, `chart_integrity` and",
        "`dashboard_aoi_match`) may abstain, so they are never implied and not",
        "counted here; they add coverage on top whenever their trigger state",
        "exists.",
        "",
        "| bucket | via dedicated check | via shared only | total | of active |",
        "|---|---|---|---|---|",
    ]
    coverage = bucket_case_coverage(active)
    for bucket in BUCKETS:
        ded = coverage[bucket]["dedicated"]
        sha = coverage[bucket]["shared_only"]
        total = ded + sha
        pct = f"{100 * total / len(active):.0f}%" if active else "—"
        lines.append(f"| {bucket} | {ded} | {sha} | {total} | {pct} |")

    lines += [
        "",
        "## Expected-field census (active cases)",
        "",
        "| field | cases | switches on |",
        "|---|---|---|",
    ]
    field_counts: Counter = Counter()
    for case in active:
        field_counts.update(case_expected_fields(case))
    for field in sorted(FIELD_CHECKS, key=lambda f: (-field_counts[f], f)):
        count = field_counts.get(field, 0)
        marker = " ← unused" if count == 0 else ""
        lines.append(f"| {field} | {count}{marker} | {FIELD_CHECKS[field]} |")
    unknown = sorted(set(field_counts) - set(FIELD_CHECKS))
    if unknown:
        lines.append("")
        lines.append(f"Fields present but not recognised here: {', '.join(unknown)}")

    dataset_lines, dataset_gap_bullets = render_dataset_section(catalog, active)
    lines += dataset_lines

    multiturn = [c for c in active if c.is_multiturn]
    delta_kinds: Counter = Counter()
    for case in multiturn:
        for turn in case.turns:
            for kind, fields in (turn.get("deltas") or {}).items():
                delta_kinds[kind] += len(fields)
    lines += [
        "",
        "## Multi-turn",
        "",
        f"{len(multiturn)} active conversations "
        f"({sum(len(c.turns) for c in multiturn)} turns). Delta assertions: "
        + (", ".join(f"{k} ×{v}" for k, v in sorted(delta_kinds.items())) or "none"),
    ]

    held = [c for c in cases if c.status.lower() in {"todo"} | ACTIVE_EXCLUDED]
    lines += [
        "",
        "## Parked and held cases",
        "",
        "| id | status | group | reason |",
        "|---|---|---|---|",
    ]
    for case in sorted(held, key=lambda c: (c.status, c.id)):
        reason = (case.notes.get("status_reason") or "—").replace("\n", " ")
        if len(reason) > 110:
            reason = reason[:107] + "..."
        lines.append(f"| {case.id} | {case.status} | {case.group} | {reason} |")

    unused = sorted(f for f in FIELD_CHECKS if field_counts.get(f, 0) == 0)
    lines += [
        "",
        "## Known gaps",
        "",
        f"- Expected fields no active case uses: {', '.join(unused) or 'none'}.",
        "  Their checks cannot fire until a case sets the field. Leave",
        "  `suggested_datasets` unused: it is legacy (the agent now writes",
        "  `nudge`), so author `nudge_type` / `nudge_options` instead.",
        f"- Info-only checks: {', '.join(sorted(INFO_ONLY))}. They run and are",
        "  reported but never affect a verdict, so the bucket coverage above",
        "  excludes them. Why each is info-only, and what would make it gate:",
        "  [evaluators README](../../src/goldset/evaluators/README.md#info-only-checks).",
        *dataset_gap_bullets,
        "- What each check measures: [evaluators README index]"
        "(../../src/goldset/evaluators/README.md#index); how to write a case:",
        "  [cases/README.md](../README.md).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cases-dir", type=Path, default=Path("cases/v2"))
    parser.add_argument(
        "--out", type=Path, default=None, help="default: <cases-dir>/COVERAGE.md"
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="zeno catalog snapshot " "(default: <cases-dir>/../zeno_catalog.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed doc is fresh; exit 1 if stale",
    )
    args = parser.parse_args()

    out = args.out or (args.cases_dir / "COVERAGE.md")
    text = render(args.cases_dir, args.catalog)
    if args.check:
        # the Last-updated stamp records when the doc was regenerated; a
        # date-only difference is not drift, so normalise it on both sides
        stamp = re.compile(r"^_Last updated: \d{4}-\d{2}-\d{2}_$", re.MULTILINE)
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if stamp.sub("_Last updated: <date>_", current) != stamp.sub(
            "_Last updated: <date>_", text
        ):
            print(
                f"{out} is stale; regenerate with: "
                f"uv run python tools/coverage_doc.py --cases-dir {args.cases_dir}"
            )
            return 1
        print(f"{out} is fresh")
        return 0
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
