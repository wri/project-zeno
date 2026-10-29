"""Markdown summary of a CI run, for the GitHub job summary and PR comment.

    uv run python tools/ci_summary.py --results-dir <dir> --out summary.md \\
        [--log gold.log] [--threshold 90] [--details-url URL]

Reads the one run record under <dir>/runs/. The headline is the pass rate,
pass / all cases, so errored and uncovered rows count against it. Below
--threshold it turns red and an ::error annotation is printed on stdout for
GitHub to pick up. When the run wrote no record (a bad token, a crash), the
summary says so and shows the tail of --log instead of a misleading 0%.

Always exits 0: CI reports eval results, it never fails on them.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.buckets import row_verdict
from goldset.ledger import RUNS_DIRNAME, read_run

VERDICTS = ("pass", "fail", "error", "uncovered")
LOG_TAIL_LINES = 40
LISTED_CASES = 50
ERROR_TRIM = 300


def find_run(results_dir: Path) -> Path | None:
    """The run record CI just wrote; it uses a fresh results dir per run."""
    runs = sorted((results_dir / RUNS_DIRNAME).glob("*.json"))
    return runs[-1] if runs else None


def count_verdicts(run: dict) -> dict[str, list[str]]:
    by_verdict: dict[str, list[str]] = {v: [] for v in VERDICTS}
    for entry in run["results"]:
        by_verdict[row_verdict(entry)].append(entry["id"])
    return by_verdict


def most_common_error(run: dict) -> tuple[str, int] | None:
    """The commonest error message and its count. A bad token or an unreachable
    deployment errors every row with the same message."""
    errors = Counter(e["error"] for e in run["results"] if e.get("error"))
    if not errors:
        return None
    return errors.most_common(1)[0]


def _format_timeout(trial_timeout: float | None) -> str:
    """``900.0`` -> ``900s``; missing on a run record predating this field."""
    return f"{trial_timeout:g}s" if trial_timeout is not None else "n/a"


def _case_list(label: str, ids: list[str]) -> list[str]:
    if not ids:
        return []
    shown = ", ".join(ids[:LISTED_CASES])
    if len(ids) > LISTED_CASES:
        shown += f", … ({len(ids) - LISTED_CASES} more)"
    return [f"**{label}:** {shown}", ""]


def render(
    run: dict, threshold: float, details_url: str | None
) -> tuple[str, str | None]:
    """The Markdown summary, and the annotation to print when below threshold."""
    by_verdict = count_verdicts(run)
    total = len(run["results"])
    passed = len(by_verdict["pass"])
    rate = 100 * passed / total if total else 0.0
    below = rate < threshold
    if below:
        headline = (
            f"🔴 **Pass rate {rate:.1f}% ({passed}/{total}), "
            f"below the {threshold:g}% threshold**"
        )
        annotation = (
            f"::error title=GOLD pass rate::{rate:.1f}% ({passed}/{total}) "
            f"is below {threshold:g}%"
        )
    else:
        headline = f"🟢 Pass rate {rate:.1f}% ({passed}/{total})"
        annotation = None

    lines = [
        "## GOLD evals",
        "",
        headline,
        "",
        "| Total | Pass | Fail | Error | Uncovered |",
        "|---|---|---|---|---|",
        f"| {total} | {passed} | {len(by_verdict['fail'])} "
        f"| {len(by_verdict['error'])} | {len(by_verdict['uncovered'])} |",
        "",
        f"Build `{run.get('build')}` · run `{run['run_id']}` · "
        f"{run.get('num_trials')} trial(s) · {run.get('workers')} worker(s) · "
        f"{_format_timeout(run.get('trial_timeout'))} trial timeout · "
        f"caseset `{run.get('caseset_version')}`",
        "",
    ]
    common = most_common_error(run)
    if common:
        message, count = common
        lines += [
            f"Most common error ({count} case(s)): `{message[:ERROR_TRIM]}`",
            "",
        ]
    failing = _case_list("Failing", by_verdict["fail"]) + _case_list(
        "Errored", by_verdict["error"]
    )
    if failing:
        lines += ["<details><summary>Cases not passing</summary>", ""]
        lines += failing
        lines += _case_list("Uncovered", by_verdict["uncovered"])
        lines += ["</details>", ""]
    if details_url:
        lines.append(
            f"Run record and HTML report: workflow artifacts on [this run]({details_url})."
        )
    return "\n".join(lines) + "\n", annotation


def render_incomplete(log: Path | None, details_url: str | None) -> tuple[str, str]:
    lines = [
        "## GOLD evals",
        "",
        "🔴 **The run did not complete: no run record was written.**",
        "",
    ]
    if log and log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()
        lines += [
            f"Last {LOG_TAIL_LINES} lines of the log:",
            "",
            "```",
            *tail[-LOG_TAIL_LINES:],
            "```",
            "",
        ]
    if details_url:
        lines.append(f"Full log: [this run]({details_url}).")
    annotation = "::error title=GOLD run::the run did not complete"
    return "\n".join(lines) + "\n", annotation


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument(
        "--threshold", type=float, default=90.0, help="pass-rate percent"
    )
    parser.add_argument("--details-url", default=None)
    args = parser.parse_args()

    path = find_run(args.results_dir)
    if path is None:
        markdown, annotation = render_incomplete(args.log, args.details_url)
    else:
        markdown, annotation = render(read_run(path), args.threshold, args.details_url)
    args.out.write_text(markdown, encoding="utf-8")
    if annotation:
        print(annotation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
