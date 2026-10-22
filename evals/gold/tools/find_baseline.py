"""Pick the committed run a new run must be diffed against.

    uv run python tools/find_baseline.py results/runs/NEW.json [--runs-dir results/runs]

Prints the path of the newest run in ``--runs-dir`` that is comparable to the
given run: same ``environment``, same ``ff`` (unset matches only unset), same
``num_trials`` and same case store (``caseset``: v1 or v2). Runs from before
2026-08-04 carry no ``caseset``; their store is unknown, so they never match a
run that records one. The given run itself is never its own baseline.
"Newest" is by the run header's ``started`` timestamp.

Exits 1 with a message when no comparable run exists. A diff across a
differing environment, ``ff``, trial count or case store measures the setup,
not the release (CLAUDE.md), so the gate must fail loudly rather than fall
back to whatever run happens to sort last.

In CI the directory holds the committed ledger plus the fresh run, so the
answer is the newest comparable committed run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.ledger import read_run

# caseset is absent (None) on runs that predate the field, and None never
# equals "v1"/"v2", so an unknown store is never guessed to match. Two such
# runs can still match each other: cases/v1 was the only store before v2
# landed on 2026-08-04, the same day the field did.
COMPARABLE_ON = ("environment", "ff", "num_trials", "caseset")
UNSET_LABEL = {"ff": "unset", "caseset": "unknown"}


def comparability(run: dict) -> tuple:
    return tuple(run.get(field) for field in COMPARABLE_ON)


def describe(run: dict) -> str:
    return ", ".join(
        f"{field}="
        f"{run.get(field) if run.get(field) is not None else UNSET_LABEL.get(field, 'unset')}"
        for field in COMPARABLE_ON
    )


def find_baseline(new_run_path: Path, runs_dir: Path) -> Path | None:
    """Newest run under ``runs_dir`` comparable to ``new_run_path``, or None."""
    new_run = read_run(new_run_path)
    wanted = comparability(new_run)
    candidates = []
    for path in sorted(runs_dir.glob("*.json")):
        if path.resolve() == new_run_path.resolve():
            continue
        run = read_run(path)
        if run["run_id"] == new_run["run_id"]:
            continue  # a copy of the new run is not a baseline either
        if comparability(run) == wanted:
            candidates.append((run["started"], run["run_id"], path))
    return max(candidates)[2] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("new_run", type=Path, help="the run to find a baseline for")
    parser.add_argument("--runs-dir", type=Path, default=Path("results/runs"))
    args = parser.parse_args()

    baseline = find_baseline(args.new_run, args.runs_dir)
    if baseline is None:
        new_run = read_run(args.new_run)
        print(
            f"no run in {args.runs_dir} is comparable to {new_run['run_id']} "
            f"({describe(new_run)}); refusing to diff against an incomparable "
            "baseline. Commit a run made with the same --env, --ff, --trials "
            "and --cases-dir first.",
            file=sys.stderr,
        )
        return 1
    print(baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
