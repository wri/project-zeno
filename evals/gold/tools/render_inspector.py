"""Render ledger runs as a standalone per-check inspection matrix.

    uv run python tools/render_inspector.py results/runs/<run_id>.json
    # -> results/reports/<run_id>_inspector.html

    uv run python tools/render_inspector.py --all
    # -> results/reports/all-runs_inspector.html (every run, dropdown)

One row per case, one column per check (grouped by bucket): pass/fail/
not-evaluated per cell, expected vs measured in the row expansion, row
verdict plus a flaky tag whenever trials disagreed. The template also
works uninjected: opened raw it accepts a run JSON by drag-and-drop.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.buckets import INFO_ONLY
from goldset.ledger import read_run

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_html import load_all_runs, load_case_contexts, merged_case_contexts

PLACEHOLDER = "__RUN_PAYLOAD__"
TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "run-inspector.html"


def _inject(payload: dict, template_text: str) -> str:
    if PLACEHOLDER not in template_text:
        raise ValueError(f"template is missing the {PLACEHOLDER} placeholder")
    text = json.dumps(payload, ensure_ascii=False)
    text = text.replace("</", "<\\/")  # keep the inline <script> JSON unterminated
    return template_text.replace(PLACEHOLDER, text)


def _inspector_payload(generated: str, cases: dict | None) -> dict:
    return {
        "info_only": sorted(INFO_ONLY),
        "generated": generated,
        "cases": cases or {},
    }


def render_inspector(
    run: dict, template_text: str, generated: str, cases: dict | None = None
) -> str:
    return _inject({"run": run, **_inspector_payload(generated, cases)}, template_text)


def render_inspector_all(
    runs: list[dict], template_text: str, generated: str, cases: dict | None = None
) -> str:
    """One self-contained matrix page embedding every run behind a dropdown."""
    return _inject(
        {"runs": list(runs), **_inspector_payload(generated, cases)}, template_text
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
        help="default: results/reports/<run_id>_inspector.html, "
        "or results/reports/all-runs_inspector.html with --all",
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
        out = args.out or args.runs_dir.parent / "reports" / "all-runs_inspector.html"
        html = render_inspector_all(runs, template_text, generated, cases=contexts)
    else:
        run = read_run(args.run)
        contexts = (
            load_case_contexts(args.cases_dir, run) if args.cases_dir.exists() else {}
        )
        out = (
            args.out
            or args.run.parents[1] / "reports" / f"{run['run_id']}_inspector.html"
        )
        html = render_inspector(run, template_text, generated, cases=contexts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
