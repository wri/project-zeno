"""Render ledger runs as standalone HTML reports.

    uv run python tools/render_html.py results/runs/<run_id>.json
    # -> results/reports/<run_id>.html

    uv run python tools/render_html.py --all
    # -> results/reports/all-runs.html (every run, run-selector dropdown)

Injects the run(s) (plus the current INFO_ONLY set, so verdict rendering
matches buckets.py) into `templates/run-report.html`. The template also
works uninjected: opened raw it accepts a run JSON by drag-and-drop.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.buckets import DEDICATED, INFO_ONLY
from goldset.ledger import read_run
from goldset.store import load_store

PLACEHOLDER = "__RUN_PAYLOAD__"
TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "run-report.html"


def _case_context(case) -> dict:
    """The plain-language context the report shows beside a failing row."""
    turns = getattr(case, "turns", ()) or ()
    context = {
        "query": case.query or (turns[0]["query"] if turns else ""),
        "group": case.group,
        "status": case.status,
        "scope": case.expected.get("scope", ""),
        "expected": dict(case.expected),
    }
    if turns:
        context["turns"] = [
            {"query": t.get("query", ""), "expected": dict(t.get("expected") or {})}
            for t in turns
        ]
    return context


def load_store_maps(cases_dir: Path) -> tuple[dict, dict]:
    """uid -> case and lineage id -> case for the current store."""
    by_uid: dict = {}
    by_id: dict = {}
    for _path, case, _uid in load_store(cases_dir):
        by_uid[case.uid] = case
        by_id[case.id] = case
    return by_uid, by_id


def case_contexts_for(run: dict, by_uid: dict, by_id: dict) -> dict[str, dict]:
    """uid -> context for every run entry resolvable in the store (uid
    first, lineage id as fallback so older runs still enrich)."""
    contexts = {}
    for entry in run.get("results", []):
        uid = entry.get("uid")
        case = by_uid.get(uid) or by_id.get(entry.get("id"))
        if uid and case is not None:
            contexts[uid] = _case_context(case)
    return contexts


def load_case_contexts(cases_dir: Path, run: dict) -> dict[str, dict]:
    by_uid, by_id = load_store_maps(cases_dir)
    return case_contexts_for(run, by_uid, by_id)


def merged_case_contexts(cases_dir: Path, runs: list[dict]) -> dict[str, dict]:
    """Case contexts for a multi-run payload: one store load, unioned by uid."""
    if not cases_dir.exists():
        return {}
    by_uid, by_id = load_store_maps(cases_dir)
    contexts: dict[str, dict] = {}
    for run in runs:
        contexts.update(case_contexts_for(run, by_uid, by_id))
    return contexts


def load_all_runs(runs_dir: Path) -> list[dict]:
    """Every ledger run in the directory, newest first, each validated."""
    paths = sorted(runs_dir.glob("*.json"), reverse=True)
    if not paths:
        raise FileNotFoundError(f"no run JSONs found in {runs_dir}")
    return [read_run(path) for path in paths]


def _inject(payload: dict, template_text: str) -> str:
    if PLACEHOLDER not in template_text:
        raise ValueError(f"template is missing the {PLACEHOLDER} placeholder")
    text = json.dumps(payload, ensure_ascii=False)
    text = text.replace("</", "<\\/")  # keep the inline <script> JSON unterminated
    return template_text.replace(PLACEHOLDER, text)


def _report_payload(generated: str, cases: dict | None) -> dict:
    return {
        "info_only": sorted(INFO_ONLY),
        "dedicated_map": dict(DEDICATED),
        "generated": generated,
        "cases": cases or {},
    }


def render_report(
    run: dict, template_text: str, generated: str, cases: dict | None = None
) -> str:
    return _inject({"run": run, **_report_payload(generated, cases)}, template_text)


def render_report_all(
    runs: list[dict], template_text: str, generated: str, cases: dict | None = None
) -> str:
    """One self-contained page embedding every run behind a dropdown."""
    return _inject(
        {"runs": list(runs), **_report_payload(generated, cases)}, template_text
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run", type=Path, nargs="?", help="results/runs/<run_id>.json")
    parser.add_argument(
        "--all",
        action="store_true",
        help="embed every run in --runs-dir behind a " "run-selector dropdown",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("results/runs"),
        help="ledger directory scanned by --all",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="default: results/reports/<run_id>.html, "
        "or results/reports/all-runs.html with --all",
    )
    parser.add_argument("--cases-dir", type=Path, default=Path("cases/v2"))
    args = parser.parse_args()
    if args.all == (args.run is not None):
        parser.error("pass exactly one of <run> or --all")

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    template_text = TEMPLATE.read_text(encoding="utf-8")
    if args.all:
        runs = load_all_runs(args.runs_dir)
        contexts = merged_case_contexts(args.cases_dir, runs)
        out = args.out or args.runs_dir.parent / "reports" / "all-runs.html"
        html = render_report_all(runs, template_text, generated, cases=contexts)
    else:
        run = read_run(args.run)
        contexts = (
            load_case_contexts(args.cases_dir, run) if args.cases_dir.exists() else {}
        )
        out = args.out or args.run.parents[1] / "reports" / f"{run['run_id']}.html"
        html = render_report(run, template_text, generated, cases=contexts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
