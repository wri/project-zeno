"""Run the zap map eval (tests/evals/zap) against the live planner.

Calls `plan_zap` for each case of one part (dev or test) with live jev and
`search_aois`, applies the plan to the case's map state as the frontend does,
and scores each field separately: dataset, area, time, context, canopy and,
for the cases that must change nothing, no_change.

    uv run python scripts/zap_eval.py dev
    uv run python scripts/zap_eval.py test --env-file ../../../.env

Needs OPENROUTER_API_KEY and DATABASE_URL (the AOI tables). The rules are in
tests/evals/zap/README.md.
"""

import argparse
import asyncio
import json
import logging
import os
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "tests" / "evals" / "zap"
FIELDS = ["dataset", "area", "time", "context", "canopy", "no_change"]
DEFAULT_CANOPY = 30
USER_ID = "zap-eval"


# --- The cases -------------------------------------------------------------


def load_part(part: str) -> tuple[date, list[dict]]:
    data = yaml.safe_load((EVAL_DIR / f"{part}.yaml").read_text())
    return date.fromisoformat(str(data["today"])), data["cases"]


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else [value]


def _str_or_none(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def current_state(case: dict) -> dict:
    """The map state before the prompt, in the field names of the eval."""
    cur = case.get("current") or {}
    area = cur.get("area")
    return {
        "dataset": cur.get("dataset"),
        "area": area["id"] if area else None,
        "area_name": area["name"] if area else None,
        "start": _str_or_none(cur.get("start")),
        "end": _str_or_none(cur.get("end")),
        "context": cur.get("context"),
        "canopy": cur.get("canopy"),
    }


def expected_state(case: dict) -> dict:
    """The expected state. A field that `expect` does not give keeps its
    value from `current` (see README.md)."""
    cur = current_state(case)
    exp = case.get("expect") or {}
    out = {
        "dataset": _as_list(exp.get("dataset", cur["dataset"])),
        "area": _as_list(exp.get("area", cur["area"])),
        "context": _as_list(exp.get("context", cur["context"])),
        "canopy": _as_list(exp.get("canopy", cur["canopy"])),
        "relative": bool(exp.get("relative", False)),
    }
    if "ranges" in exp:
        out["ranges"] = [tuple(map(_str_or_none, r)) for r in exp["ranges"]]
    else:
        start = exp["start"] if "start" in exp else cur["start"]
        end = exp["end"] if "end" in exp else cur["end"]
        out["ranges"] = [(_str_or_none(start), _str_or_none(end))]
    return out


def zap_current(case: dict):
    """The `ZapCurrent` for the case. Only the fields that the model has are
    sent, so a later model with more fields gets them with no change here."""
    from src.api.services.zap.models import ZapArea, ZapCurrent

    cur = current_state(case)
    area = None
    if cur["area"]:
        source, src_id = cur["area"].split(":", 1)
        area = ZapArea(name=cur["area_name"], source=source, src_id=src_id)
    values = {
        "dataset_id": cur["dataset"],
        "area": area,
        "start_date": cur["start"],
        "end_date": cur["end"],
        "context_layer": cur["context"],
        "canopy_cover": cur["canopy"],
    }
    fields = ZapCurrent.model_fields
    return ZapCurrent(
        **{k: v for k, v in values.items() if k in fields and v is not None}
    )


# --- Plan to state ---------------------------------------------------------


def _canopy_of(dataset_args: dict) -> Optional[int]:
    for param in dataset_args.get("parameters") or []:
        if param.get("name") == "canopy_cover" and param.get("values"):
            return int(param["values"][0])
    return None


def state_after(case: dict, plan) -> dict:
    """The map state after the frontend runs the plan on the case state.

    A dataset step sets the dataset, the dates, the context layer and the
    canopy cover. An area step sets the area. With no step for a part, the
    map keeps what it shows.
    """
    state = current_state(case)
    state.pop("area_name")
    for step in plan.steps:
        if step.kind == "dataset":
            args = step.args
            state.update(
                dataset=args["dataset_id"],
                start=str(args["start_date"]),
                end=str(args["end_date"]),
                context=args.get("context_layer"),
                canopy=_canopy_of(args),
            )
        elif step.kind == "area":
            state["area"] = f"{step.args['source']}:{step.args['src_id']}"
    return state


# --- Scoring ---------------------------------------------------------------


def _days(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


async def clamp(
    start: Optional[str],
    end: Optional[str],
    dataset_id: int,
    context: Optional[str],
) -> tuple[str, str]:
    """A range as the planner shows it for the dataset: clamped to the
    dataset's dates, or all of them when the range is outside the dataset."""
    from src.agent.datasets.dates import revise_date_range

    start, end, _ = await revise_date_range(start, end, dataset_id, context)
    if start > end:
        start, end, _ = await revise_date_range(
            None, None, dataset_id, context
        )
    return str(start), str(end)


async def range_ok(got: dict, exp: dict) -> bool:
    """True when the shown range matches one expected range. The expected
    range is clamped to the dataset that the plan shows, so a wrong dataset
    is not counted again as a wrong time. A fixed range must match to the
    day. A range back from today must end within 1 day and start within a
    fifth of its length (stac-zap eval/score.ts)."""
    if got["dataset"] is None or got["start"] is None:
        return False
    for start, end in exp["ranges"]:
        want = await clamp(start, end, got["dataset"], got["context"])
        have = (got["start"], got["end"])
        if not exp["relative"]:
            if have == want:
                return True
            continue
        tolerance = max(1, _days(want[0], want[1]) // 5)
        if (
            _days(have[1], want[1]) <= 1
            and _days(have[0], want[0]) <= tolerance
        ):
            return True
    return False


def _has_context(dataset_id: Optional[int]) -> bool:
    from src.api.services.zap.planner import CATALOG

    return bool((CATALOG.get(dataset_id) or {}).get("context_layers"))


def _has_canopy(dataset_id: Optional[int]) -> bool:
    from src.api.services.zap.planner import CATALOG, _canopy_values

    ds = CATALOG.get(dataset_id)
    return bool(ds and _canopy_values(ds))


def _canopy_norm(value: Optional[int]) -> int:
    return DEFAULT_CANOPY if value is None else int(value)


async def score(case: dict, got: dict, plan) -> dict[str, Optional[bool]]:
    """One result per field: True, False, or None when the field is not
    scored for this case."""
    exp = expected_state(case)
    skip = set(case.get("skip") or [])
    datasets = exp["dataset"]
    has_dataset = any(d is not None for d in datasets)
    out: dict[str, Optional[bool]] = dict.fromkeys(FIELDS)
    out["dataset"] = got["dataset"] in datasets
    out["area"] = got["area"] in exp["area"]
    if has_dataset and "time" not in skip:
        out["time"] = await range_ok(got, exp)
    if any(_has_context(d) for d in datasets) and "context" not in skip:
        out["context"] = got["context"] in exp["context"]
    if any(_has_canopy(d) for d in datasets) and "canopy" not in skip:
        out["canopy"] = _canopy_norm(got["canopy"]) in {
            _canopy_norm(c) for c in exp["canopy"]
        }
    if case.get("no_change"):
        out["no_change"] = not plan.steps
    for field in skip:
        out[field] = None
    return out


# --- Running ---------------------------------------------------------------


def _quiet_logs() -> None:
    import structlog

    logging.basicConfig(level=logging.WARNING)
    for name in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING)
    )


def _fix_today(today: date) -> None:
    """`revise_date_range` ends an open dataset (integrated alerts) on the
    real date. Fix it to the date of the eval so that the run repeats."""
    import src.agent.datasets.dates as dates

    class _EvalDate(date):
        @classmethod
        def today(cls):
            return today

    dates.date = _EvalDate


async def run_case(case: dict, today: date) -> dict:
    from src.api.services.zap.planner import plan_zap

    started = time.perf_counter()
    try:
        plan = await plan_zap(
            case["prompt"], zap_current(case), USER_ID, today=today
        )
        error = None
    except Exception as exc:  # noqa: BLE001 - a failed case is a result
        plan, error = None, f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000)

    if plan is None:
        scores = {
            f: False
            for f, v in (
                await score(case, current_state(case), _NoPlan)
            ).items()
            if v is not None
        }
        got = None
    else:
        got = state_after(case, plan)
        scores = {
            f: v
            for f, v in (await score(case, got, plan)).items()
            if v is not None
        }
    return {
        "id": case["id"],
        "kind": case.get("kind"),
        "tests": case.get("tests") or [],
        "prompt": case["prompt"],
        "expected": expected_state(case),
        "got": got,
        "scores": scores,
        "latency_ms": latency_ms,
        "error": error,
        "plan": slim_plan(plan.model_dump()) if plan else None,
    }


# The keys of a dataset step that the results file keeps. The other keys are
# the long catalog texts of the dataset.
DATASET_KEYS = (
    "dataset_id",
    "dataset_name",
    "start_date",
    "end_date",
    "context_layer",
    "parameters",
    "tile_url",
)


def slim_plan(plan: dict) -> dict:
    for step in plan["steps"]:
        if step["kind"] == "dataset":
            step["args"] = {k: step["args"].get(k) for k in DATASET_KEYS}
    return plan


class _NoPlan:
    steps: list = []


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def report(results: list[dict], meta: dict) -> str:
    lines = [
        f"Zap eval, part {meta['part']}: {len(results)} cases, "
        f"jev model {meta['jev_model']}, today {meta['today']}",
        "",
        "| Field | Correct | Scored | % |",
        "|---|---|---|---|",
    ]
    for field in FIELDS:
        scored = [r["scores"][field] for r in results if field in r["scores"]]
        if scored:
            ok = sum(scored)
            lines.append(
                f"| {field} | {ok} | {len(scored)} | {100 * ok / len(scored):.0f} |"
            )
    all_ok = sum(all(r["scores"].values()) for r in results)
    lines.append(
        f"| all fields of a case | {all_ok} | {len(results)} | "
        f"{100 * all_ok / len(results):.0f} |"
    )

    # The tested fields, per kind of case.
    by_kind: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        tested = [r["scores"][f] for f in r["tests"] if f in r["scores"]]
        by_kind[r["kind"]].append(all(tested))
    lines += ["", "| Kind | Tested fields correct | Cases |", "|---|---|---|"]
    for kind, oks in sorted(by_kind.items()):
        lines.append(f"| {kind} | {sum(oks)} | {len(oks)} |")

    latencies = [r["latency_ms"] for r in results if not r["error"]]
    if latencies:
        lines += ["", f"Median latency: {statistics.median(latencies):.0f} ms"]
    errors = Counter(r["error"].split(":")[0] for r in results if r["error"])
    if errors:
        lines.append(f"Errors: {dict(errors)}")

    lines += ["", "Failed fields:"]
    for r in results:
        failed = [f for f, v in r["scores"].items() if not v]
        if not failed:
            continue
        got = r["got"] or {}
        exp = r["expected"]
        detail = []
        for f in failed:
            if f == "time":
                detail.append(
                    f"time {got.get('start')}..{got.get('end')} "
                    f"(want {exp['ranges']})"
                )
            elif f == "no_change":
                steps = len(r["plan"]["steps"]) if r["plan"] else "no plan"
                detail.append(f"no_change: {steps} steps")
            else:
                detail.append(f"{f} {got.get(f)} (want {exp[f]})")
        if r["error"]:
            detail.append(r["error"])
        lines.append(f'- {r["id"]} "{r["prompt"]}": ' + "; ".join(detail))
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("part", choices=["dev", "test"])
    parser.add_argument(
        "--env-file",
        default=".env",
        help="The .env file with OPENROUTER_API_KEY and DATABASE_URL.",
    )
    parser.add_argument(
        "--out",
        default=str(EVAL_DIR / "results"),
        help="The directory for the results file.",
    )
    parser.add_argument("--ids", nargs="*", help="Run only these case ids.")
    parser.add_argument("--label", default="", help="Added to the file name.")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(args.env_file)

    from src.api.config import APISettings
    from src.api.services.zap import planner  # noqa: F401 - logging setup
    from src.shared.database import close_global_pool, initialize_global_pool

    _quiet_logs()

    if not APISettings.openrouter_api_key:
        sys.exit("OPENROUTER_API_KEY is not set")
    if not os.environ.get("DATABASE_URL"):
        sys.exit("DATABASE_URL is not set")

    today, cases = load_part(args.part)
    if args.ids:
        cases = [c for c in cases if c["id"] in set(args.ids)]
    _fix_today(today)
    await initialize_global_pool()
    results = []
    try:
        for case in cases:
            result = await run_case(case, today)
            mark = "ok" if all(result["scores"].values()) else "FAIL"
            print(
                f"{result['id']} {mark} {result['latency_ms']} ms", flush=True
            )
            results.append(result)
    finally:
        await close_global_pool()

    meta = {
        "part": args.part,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": str(today),
        "jev_model": APISettings.jev_model,
        "git_sha": _git_sha(),
    }
    text = report(results, meta)
    print("\n" + text)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    label = f"-{args.label}" if args.label else ""
    path = out_dir / f"{stamp}-{args.part}{label}.json"
    path.write_text(
        json.dumps({"meta": meta, "results": results}, indent=1, default=str)
        + "\n"
    )
    print(f"\nResults: {path}")


if __name__ == "__main__":
    asyncio.run(main())
