"""Render every ledger run into a standalone performance-trends page.

    uv run python tools/render_trends.py
    # -> results/reports/trends.html

A run-over-run ticker: overall pass rate (one line per ff profile, never
drawn across differing tool profiles), KPI tiles with deltas against the
previous comparable run, and per-bucket small multiples. Question-set
version changes are marked on the axis. The template also works
uninjected: opened raw it accepts run JSONs by drag-and-drop.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_html import load_all_runs

PLACEHOLDER = "__RUN_PAYLOAD__"
TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "run-trends.html"


def render_trends(runs: list[dict], template_text: str, generated: str) -> str:
    if PLACEHOLDER not in template_text:
        raise ValueError(f"template is missing the {PLACEHOLDER} placeholder")
    payload = json.dumps(
        {"runs": list(runs), "generated": generated}, ensure_ascii=False
    ).replace("</", "<\\/")  # keep the inline <script> JSON unterminated
    return template_text.replace(PLACEHOLDER, payload)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("results/runs"),
        help="ledger directory to chart",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="default: results/reports/trends.html"
    )
    args = parser.parse_args()

    runs = load_all_runs(args.runs_dir)
    out = args.out or args.runs_dir.parent / "reports" / "trends.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out.write_text(
        render_trends(runs, TEMPLATE.read_text(encoding="utf-8"), generated),
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
