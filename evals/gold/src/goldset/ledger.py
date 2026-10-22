"""The results ledger: build, validate, read and write run records.

The record format is defined in ``results/README.md``: results key on case
``uid`` and ``caseset_version``, checks are tri-state (``1.0`` / ``0.0`` /
``None``), and nothing is ever hand-written into the ledger.

The CSV helpers (``check_name_from_column``, ``parse_score``,
``majority_from_mean``) serve ``tools/ingest_run.py``, which imports legacy
gnw-evals result CSVs. One naming quirk is handled here, in ``REASON_ALIASES``:
the score is ``charts_answer_score`` but its reason field is
``chart_answer_score_reason``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

RUNS_DIRNAME = "runs"
PARTIAL_SUFFIX = ".partial.jsonl"

# reason-column stem -> check name (gnw-evals historical inconsistency)
REASON_ALIASES = {"chart_answer": "charts_answer"}

# score columns that are aggregates or diagnostics, not checks
NON_CHECK_SCORES = {"overall_score"}

_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z_[a-z]+(_[a-z0-9-]+)?$")

REQUIRED_RUN_FIELDS = (
    "run_id",
    "started",
    "environment",
    "build",
    "ff",
    "harness",
    "judge_model",
    "num_trials",
    "caseset_version",
    "results",
)


def check_name_from_column(column: str) -> str | None:
    """Map a harness CSV column to a check name, or None if not a check."""
    if column in NON_CHECK_SCORES or column.endswith("_score_std"):
        return None
    if column.endswith("_score"):
        return column.removesuffix("_score")
    return None


def reason_name_from_column(column: str) -> str | None:
    if column.endswith("_score_reason"):
        stem = column.removesuffix("_score_reason")
        return REASON_ALIASES.get(stem, stem)
    if column.endswith("_reason"):
        # deterministic validators write plain <check>_reason fields
        return column.removesuffix("_reason")
    return None


def parse_score(cell: object) -> float | None:
    """Tri-state parse: empty -> None (not evaluated), else 1.0/0.0."""
    text = str(cell or "").strip()
    if not text:
        return None
    value = float(text)
    if value not in (0.0, 1.0):
        raise ValueError(f"check scores must be binary, got {value!r}")
    return value


def majority(values: list[float | None]) -> float | None:
    """Majority verdict across trials. None if never evaluated; ties fail
    conservatively."""
    evaluated = [v for v in values if v is not None]
    if not evaluated:
        return None
    passes = sum(1 for v in evaluated if v == 1.0)
    return 1.0 if passes * 2 > len(evaluated) else 0.0


def majority_from_mean(cell: object, num_trials: int) -> float | None:
    """Majority verdict recovered from a trial-mean score column.

    Multi-trial gnw-evals CSVs write the mean of the per-trial scores into
    the primary ``*_score`` column, so the pass count is ``mean * trials``.
    A mean that doesn't correspond to a whole number of passes (e.g. some
    trials returned None and shrank the denominator) is refused loudly
    rather than mis-ingested. Ties fail conservatively, as in ``majority``.
    """
    text = str(cell or "").strip()
    if not text:
        return None
    mean = float(text)
    passes = round(mean * num_trials)
    if not 0 <= passes <= num_trials or abs(mean - passes / num_trials) > 0.005:
        raise ValueError(
            f"{mean!r} is not a mean of {num_trials} binary scores — "
            "were some trials unevaluated? ingest per-trial data instead"
        )
    return 1.0 if passes * 2 > num_trials else 0.0


def make_run_id(started_utc: str, environment: str, ff: str | None) -> str:
    """``<YYYYMMDD>T<HHMMSS>Z_<env>[_<ff>]`` from an ISO-8601 UTC timestamp."""
    compact = re.sub(r"[-:]", "", started_utc.split(".")[0]).removesuffix("Z")
    if not re.fullmatch(r"\d{8}T\d{6}", compact):
        raise ValueError(f"cannot derive run_id from started={started_utc!r}")
    run_id = f"{compact}Z_{environment}"
    if ff:
        run_id += f"_{ff}"
    return run_id


def validate_run(run: dict) -> list[str]:
    """Contract violations; empty list means the record is well-formed."""
    problems = [f"missing field: {f}" for f in REQUIRED_RUN_FIELDS if f not in run]
    if problems:
        return problems
    if not _RUN_ID_RE.match(run["run_id"]):
        problems.append(f"malformed run_id: {run['run_id']!r}")
    if not isinstance(run["results"], list) or not run["results"]:
        problems.append("results must be a non-empty list")
        return problems
    for i, entry in enumerate(run["results"]):
        label = entry.get("id") or f"results[{i}]"
        if not entry.get("uid") and not entry.get("stale_case"):
            problems.append(f"{label}: no uid and not marked stale_case")
        if "checks" not in entry or not isinstance(entry["checks"], dict):
            problems.append(f"{label}: missing checks mapping")
            continue
        for name, value in entry["checks"].items():
            if value is None:
                continue
            # bool == float equivalence would let True/1 slip through an
            # `in (0.0, 1.0)` test; the contract is floats only.
            if not isinstance(value, float) or value not in (0.0, 1.0):
                problems.append(f"{label}: check {name} = {value!r} (not tri-state)")
    return problems


def write_run(results_dir: Path, run: dict) -> Path:
    problems = validate_run(run)
    if problems:
        raise ValueError(f"refusing to write invalid run: {problems}")
    runs_dir = results_dir / RUNS_DIRNAME
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{run['run_id']}.json"
    content = json.dumps(run, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ValueError(
            f"{path} exists with different content — runs are immutable; "
            "delete the file first if this re-ingest is intentional"
        )
    path.write_text(content, encoding="utf-8")
    return path


# Everything a resumed invocation needs to reconstruct the run's config:
# flags on a --resume invocation are ignored in favour of these, so the two
# halves of a resumed run cannot diverge.
REQUIRED_PARTIAL_HEADER_FIELDS = (
    "run_id",
    "started",
    "environment",
    "resolved_url",
    "ff",
    "build",
    "trials",
    "workers",
    "trial_timeout",
    "slow_threshold",
    "cases_dir",
    "caseset_version",
    "status_exclude",
    "id",
    "group",
    "note",
)


def partial_path(results_dir: Path, run_id: str) -> Path:
    return results_dir / RUNS_DIRNAME / f"{run_id}{PARTIAL_SUFFIX}"


def _append_jsonl(path: Path, obj: dict) -> None:
    # One fsynced line per completed case: a kill can truncate at most the
    # final line, which read_partial discards (that case simply re-runs).
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_partial_header(results_dir: Path, header: dict) -> Path:
    missing = [f for f in REQUIRED_PARTIAL_HEADER_FIELDS if f not in header]
    if missing:
        raise ValueError(f"partial header missing fields: {missing}")
    path = partial_path(results_dir, header["run_id"])
    if path.exists():
        raise ValueError(f"{path} already exists — resume or delete it first")
    path.parent.mkdir(parents=True, exist_ok=True)
    _append_jsonl(path, header)
    return path


def append_partial_entry(path: Path, entry: dict) -> None:
    _append_jsonl(path, entry)


def read_partial(path: Path) -> tuple[dict, list[dict]]:
    """Header + completed entries from an in-flight run file.

    A truncated final line is the expected signature of a killed run and is
    dropped; corruption anywhere else is refused loudly.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path} is empty — no header to resume from")
    parsed: list[dict] = []
    for number, line in enumerate(lines, start=1):
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            if number == len(lines):
                break
            raise ValueError(f"{path}:{number}: corrupt line mid-file") from None
    if not parsed:
        raise ValueError(f"{path}: header line is unreadable")
    header, entries = parsed[0], parsed[1:]
    missing = [f for f in REQUIRED_PARTIAL_HEADER_FIELDS if f not in header]
    if missing:
        raise ValueError(f"{path}: first line is not a run header ({missing=})")
    seen: set[str] = set()
    for entry in entries:
        uid = entry.get("uid")
        if not uid or "checks" not in entry:
            raise ValueError(f"{path}: entry without uid/checks: {entry!r:.120}")
        if uid in seen:
            raise ValueError(
                f"{path}: duplicate entry for uid {uid} — "
                "was the run resumed twice in parallel?"
            )
        seen.add(uid)
    return header, entries


def read_run(path: Path) -> dict:
    run = json.loads(path.read_text(encoding="utf-8"))
    problems = validate_run(run)
    if problems:
        raise ValueError(f"{path}: invalid run record: {problems}")
    return run
