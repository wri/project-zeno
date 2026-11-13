"""Run the zap evals (tests/evals/zap) against the live planner.

Calls `plan_zap` for each case of one part (dev or test) with live jev and
`search_aois`, applies the plan to the case's map state as the frontend does,
and scores each field separately: dataset, area, time, context, canopy and,
for the cases that must change nothing, no_change.

    uv run python scripts/zap_eval.py dev
    uv run python scripts/zap_eval.py test --env-file ../../../.env
    uv run python scripts/zap_eval.py dashboard-dev --env-file ../../../.env

The dashboard parts (`dashboard-dev`, `dashboard-test`) run against the
fixed dashboards of `dashboards.yaml` and score the action, the dataset,
the time, the forest type, the canopy cover, the template, the cloud cover
and the confirmation. They need no database.

A follow-up case (`follows`) sends the state after its first prompt
(`ZapPlan.state`) as `current`, as the frontend does. `--no-chain` sends the
fixed `current` of the case instead.

Needs OPENROUTER_API_KEY, and DATABASE_URL (the AOI tables) for the map
parts. The rules are in
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


def state_of(current) -> dict:
    """A `ZapCurrent` in the field names of the eval."""
    area = current.area
    return {
        "dataset": current.dataset_id,
        "area": f"{area.source}:{area.src_id}" if area else None,
        "start": _str_or_none(getattr(current, "start_date", None)),
        "end": _str_or_none(getattr(current, "end_date", None)),
        "context": getattr(current, "context_layer", None),
        "canopy": getattr(current, "canopy_cover", None),
    }


def state_after(case: dict, plan, before: Optional[dict] = None) -> dict:
    """The map state after the frontend runs the plan on the state before
    it (`before`, else the case state).

    A dataset step sets the dataset, the dates, the context layer and the
    canopy cover. An area step sets the area. With no step for a part, the
    map keeps what it shows.
    """
    state = dict(before) if before else current_state(case)
    state.pop("area_name", None)
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


# --- The dashboard set -----------------------------------------------------
# The cases run against the fixed dashboards of dashboards.yaml. The script
# gives the planner a `ZapDashboard` for each, so the run needs no database.

DASHBOARD_FIELDS = [
    "action",
    "dataset",
    "time",
    "context",
    "canopy",
    "template",
    "cloud",
    "target",
    "destination",
    "size",
    "title",
    "widgets",
    "tier",
    "confirm",
]
# The fields that make a plan wrong when they are wrong: an addition, an
# edit or a removal that the user did not ask for.
ADDITION_FIELDS = [f for f in DASHBOARD_FIELDS if f not in ("tier", "confirm")]
ADD_KINDS = ("add_chart", "add_map", "add_template", "add_imagery")
EDIT_KINDS = (
    "add_section",
    "move",
    "resize",
    "rename",
    "change_period",
    "remove",
)
DEFAULT_CLOUD = 20


WIDGET_TYPES = {
    "chart": ("insight", "Chart"),
    "map": ("map", "Map"),
    "imagery": ("map", "Imagery"),
    "alerts": ("alerts", "Alerts list"),
    "note": ("text", "Note"),
}


def _board_widget(raw: Any, position: int):
    """A `BoardWidget` from a widget of dashboards.yaml or of a case."""
    from src.api.services.zap.board import BoardWidget

    if isinstance(raw, str):
        return raw
    widget_type, kind = WIDGET_TYPES[raw["kind"]]
    config = dict(raw.get("config") or {})
    if raw["kind"] == "imagery":
        config.setdefault("imagery", {"mosaic_id": "eval"})
    analysis = raw.get("analysis")
    if analysis:
        analysis = {
            "dataset_id": analysis["dataset"],
            "start_date": _str_or_none(analysis.get("start")),
            "end_date": _str_or_none(analysis.get("end")),
            "context_layer": analysis.get("context"),
            "canopy_cover": analysis.get("canopy"),
        }
    return BoardWidget(
        id=raw["id"],
        widget_type=widget_type,
        title=raw["title"],
        kind=kind,
        position=raw.get("position", position),
        section_id=raw.get("section"),
        config=config,
        insight_id=f"insight-{raw['id']}"
        if widget_type == "insight"
        else None,
        analysis=analysis,
    )


def _board(raw: dict, extra_sections=(), extra_widgets=()):
    from src.api.services.zap.board import BoardSection
    from src.api.services.zap.dashboard import ZapDashboard
    from src.api.services.zap.models import ZapArea

    source, src_id = raw["area"]["id"].split(":", 1)
    sections = [*(raw.get("sections") or []), *extra_sections]
    widgets = [*(raw.get("widgets") or []), *extra_widgets]
    area = ZapArea(
        name=raw["area"]["name"],
        source=source,
        src_id=src_id,
        subtype=raw["area"]["subtype"],
    )
    if all(isinstance(w, str) for w in widgets) and all(
        isinstance(x, str) for x in sections
    ):
        # The text form of phase 4.
        return ZapDashboard(
            id=raw["id"],
            name=raw["name"],
            area=area,
            sections=sections,
            widgets=widgets,
        )
    return ZapDashboard(
        id=raw["id"],
        name=raw["name"],
        area=area,
        section_items=[
            BoardSection(id=x["id"], title=x["title"], position=i)
            for i, x in enumerate(sections)
        ],
        widget_items=[_board_widget(w, i) for i, w in enumerate(widgets)],
    )


def load_dashboards() -> dict:
    data = yaml.safe_load((EVAL_DIR / "dashboards.yaml").read_text())
    return {key: raw for key, raw in data["dashboards"].items()}


def case_board(case: dict, boards: dict):
    """The dashboard of a case: the fixed dashboard, with the sections and
    the widgets that the last edit added (`add_sections`, `add_widgets`)."""
    return _board(
        boards[case["dashboard"]],
        case.get("add_sections") or (),
        case.get("add_widgets") or (),
    )


def dashboard_current(case: dict, board):
    """The `ZapCurrent` of a dashboard case: the page, the dashboard id and
    the state of the last addition (`current`), if the case gives one."""
    from src.api.services.zap.models import ZapCurrent

    cur = current_state(case)
    values = {
        "dataset_id": cur["dataset"],
        "start_date": cur["start"],
        "end_date": cur["end"],
        "context_layer": cur["context"],
        "canopy_cover": cur["canopy"],
    }
    last = case.get("last") or []
    values["last_widget_ids"] = [i for i in last if not i.startswith("sec-")]
    values["last_section_ids"] = [i for i in last if i.startswith("sec-")]
    return ZapCurrent(
        page="dashboard",
        dashboard_id=board.id,
        **{k: v for k, v in values.items() if v},
    )


def dashboard_expected(case: dict) -> dict:
    exp = case.get("expect") or {}
    out = {
        "action": _as_list(exp.get("action", "none")),
        "dataset": _as_list(exp.get("dataset")),
        "context": _as_list(exp.get("context")),
        "canopy": _as_list(exp.get("canopy")),
        "template": _as_list(exp.get("template")),
        "cloud": _as_list(exp.get("cloud", DEFAULT_CLOUD)),
        "target": _as_list(exp.get("target")),
        "destination": _as_list(exp.get("destination")),
        "size": _as_list(exp.get("size")),
        "title": _as_list(exp.get("title")),
        "widgets": _as_list(exp.get("widgets", False)),
        "confirm": exp.get("confirm", "any"),
        "tier": exp.get(
            "tier",
            {True: 2, False: 1}.get(exp.get("confirm"))
            if isinstance(exp.get("confirm"), bool)
            else None,
        ),
        "relative": bool(exp.get("relative", False)),
        "has_time": "ranges" in exp or "start" in exp or "end" in exp,
    }
    if "ranges" in exp:
        out["ranges"] = [tuple(map(_str_or_none, r)) for r in exp["ranges"]]
    else:
        out["ranges"] = [
            (_str_or_none(exp.get("start")), _str_or_none(exp.get("end")))
        ]
    return out


ACTION_TEXTS: dict = {}


def _jev_action(plan) -> Optional[str]:
    """The `action` option that jev selected, from its decision label."""
    from src.api.services.zap import options as o

    if not ACTION_TEXTS:
        for key, text in o.ACTIONS.items():
            # The planner cuts a label of more than 80 characters.
            ACTION_TEXTS[text] = key
            ACTION_TEXTS[text[:77] + "..."] = key
    for d in plan.decisions:
        if d.question == "Action":
            return ACTION_TEXTS.get(d.label, d.label)
    return None


def dashboard_got(plan) -> dict:
    """What the plan adds, in the field names of the eval."""
    got: dict = {
        "action": "none",
        "jev_action": _jev_action(plan),
        "dataset": None,
        "start": None,
        "end": None,
        "context": None,
        "canopy": None,
        "template": None,
        "cloud": None,
        "target_date": None,
        "window_days": None,
        "target": None,
        "destination": None,
        "size": None,
        "title": None,
        "widgets": None,
        "needs_confirmation": plan.needs_confirmation,
        "tier": plan.tier,
    }
    if not plan.steps:
        return got
    step = plan.steps[0]
    args = step.args
    got["action"] = step.kind
    if step.kind == "add_chart":
        body = args["analyze"]
        got.update(
            dataset=body["dataset_id"],
            start=body["start_date"],
            end=body["end_date"],
            context=body.get("context_layer"),
            canopy=body.get("canopy_cover"),
        )
    elif step.kind == "add_map":
        layer = args["widget"]["config"]["dataset"]
        got.update(
            dataset=layer["dataset_id"],
            start=str(layer["start_date"]),
            end=str(layer["end_date"]),
            context=layer.get("context_layer"),
            canopy=_canopy_of(layer),
        )
    elif step.kind == "add_template":
        got["template"] = args["template"]
    elif step.kind == "add_imagery":
        mosaic = args["mosaic"]
        got.update(
            target_date=mosaic["target_date"],
            window_days=mosaic["window_days"],
            cloud=mosaic["max_cloud_cover"],
        )
    elif step.kind == "add_section":
        got["title"] = args["section"]["title"]
    elif step.kind == "move":
        got.update(
            target=args["widget_id"],
            destination=args["patch"]["section_id"] or "top",
        )
    elif step.kind == "resize":
        got.update(target=args["widget_id"], size=args["size"])
    elif step.kind == "rename":
        got.update(
            target=args["section_id"] or "dashboard", title=args["title"]
        )
    elif step.kind == "change_period":
        got["target"] = args["widget_id"]
        if args.get("analyze"):
            body = args["analyze"]
            got.update(
                dataset=body["dataset_id"],
                start=body["start_date"],
                end=body["end_date"],
                context=body.get("context_layer"),
            )
        else:
            layer = args["widget"]["config"]["dataset"]
            got.update(
                dataset=layer["dataset_id"],
                start=str(layer["start_date"]),
                end=str(layer["end_date"]),
                context=layer.get("context_layer"),
            )
    elif step.kind == "remove":
        got.update(
            target=args["widget_id"] or args["section_id"],
            widgets=args["delete_widgets"]
            if args["target_type"] == "section"
            else None,
        )
    return got


def imagery_ok(got: dict, exp: dict, today: date) -> bool:
    """The target date and the window of the imagery agree with the ones
    that the expected range gives. A range back from today has a tolerance
    of 1 day on the target and a fifth on the window."""
    from src.api.services.zap.dashboard import _imagery_window

    for start, end in exp["ranges"]:
        rng = None if (start, end) == (None, None) else (start, end)
        target, window = _imagery_window(rng, today)
        if not exp["relative"]:
            if (got["target_date"], got["window_days"]) == (
                str(target),
                window,
            ):
                return True
            continue
        if _days(got["target_date"], str(target)) <= 1 and abs(
            got["window_days"] - window
        ) <= max(1, window // 5):
            return True
    return False


async def dashboard_score(
    case: dict, got: dict, today: date
) -> dict[str, Optional[bool]]:
    """One result per field: True, False, or None when the field is not
    scored for this case. The fields of an addition are scored only when
    the expected action is an addition."""
    exp = dashboard_expected(case)
    out: dict[str, Optional[bool]] = dict.fromkeys(DASHBOARD_FIELDS)
    out["action"] = got["action"] in exp["action"]
    if got["action"] != "none":
        if isinstance(exp["confirm"], bool):
            out["confirm"] = bool(got["needs_confirmation"]) == exp["confirm"]
        if exp["tier"] is not None:
            out["tier"] = got["tier"] == exp["tier"]
    edits = [a for a in exp["action"] if a in EDIT_KINDS]
    if edits and got["action"] in edits:
        kind = got["action"]
        if kind != "add_section":
            out["target"] = got["target"] in exp["target"]
        if kind == "move":
            out["destination"] = got["destination"] in exp["destination"]
        if kind == "resize":
            out["size"] = got["size"] in exp["size"]
        if kind in ("rename", "add_section"):
            out["title"] = got["title"] in exp["title"]
        if kind == "remove" and got["widgets"] is not None:
            out["widgets"] = got["widgets"] in exp["widgets"]
        if kind == "change_period" and exp["has_time"]:
            out["time"] = await range_ok(got, exp)
        return out
    adds = [a for a in exp["action"] if a in ADD_KINDS]
    if not adds or got["action"] == "none":
        return out
    data_actions = {"add_chart", "add_map"}
    if data_actions & set(adds) and got["action"] in data_actions:
        datasets = exp["dataset"]
        out["dataset"] = got["dataset"] in datasets
        if exp["has_time"]:
            out["time"] = await range_ok(got, exp)
        if any(_has_context(d) for d in datasets):
            out["context"] = got["context"] in exp["context"]
        if any(_has_canopy(d) for d in datasets):
            out["canopy"] = _canopy_norm(got["canopy"]) in {
                _canopy_norm(c) for c in exp["canopy"]
            }
    if "add_template" in adds and got["action"] == "add_template":
        out["template"] = got["template"] in exp["template"]
    if "add_imagery" in adds and got["action"] == "add_imagery":
        out["time"] = imagery_ok(got, exp, today)
        out["cloud"] = got["cloud"] in exp["cloud"]
    return out


async def run_dashboard_case(case: dict, today: date, boards: dict) -> dict:
    from src.api.services.zap.planner import plan_zap

    board = case_board(case, boards)
    sent = dashboard_current(case, board)
    started = time.perf_counter()
    try:
        plan = await plan_zap(
            case["prompt"],
            sent,
            USER_ID,
            today=today,
            dashboard=board,
            choose=case.get("choose"),
        )
        error = None
    except Exception as exc:  # noqa: BLE001 - a failed case is a result
        plan, error = None, f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000)
    got = dashboard_got(plan) if plan else None
    if plan is None:
        scores = {"action": False}
    else:
        scores = {
            f: v
            for f, v in (await dashboard_score(case, got, today)).items()
            if v is not None
        }
    added = bool(plan and plan.steps)
    wrong = added and any(
        scores.get(f) is False for f in ADDITION_FIELDS if f in scores
    )
    exp = dashboard_expected(case)
    kind = got["action"] if got else "none"
    group = (
        "removal"
        if kind == "remove"
        else "edit"
        if kind in EDIT_KINDS
        else "addition"
    )
    confirmed = bool(plan and plan.needs_confirmation)
    return {
        "group": group if added else None,
        "id": case["id"],
        "kind": case.get("kind"),
        "dashboard": case["dashboard"],
        "prompt": case["prompt"],
        "expected": exp,
        "got": got,
        "scores": scores,
        "added": added,
        "wrong_addition": wrong,
        "wrong_unconfirmed": wrong and not (plan and plan.needs_confirmation),
        "extra_confirmation": bool(
            added and not wrong and confirmed and exp["confirm"] is False
        ),
        "latency_ms": latency_ms,
        "error": error,
        "unclear": [
            d.question
            for d in (plan.decisions if plan else [])
            if d.clear is False
        ],
        "plan": plan.model_dump() if plan else None,
    }


def dashboard_report(results: list[dict], meta: dict) -> str:
    lines = [
        f"Zap dashboard eval, part {meta['part']}: {len(results)} cases, "
        f"jev model {meta['jev_model']}, extraction model "
        f"{meta.get('extract_model')}, today {meta['today']}",
        "",
        "| Field | Correct | Scored | % |",
        "|---|---|---|---|",
    ]
    for field in DASHBOARD_FIELDS:
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
    by_kind: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_kind[r["kind"]].append(all(r["scores"].values()))
    lines += ["", "| Kind | All fields correct | Cases |", "|---|---|---|"]
    for kind, oks in sorted(by_kind.items()):
        lines.append(f"| {kind} | {sum(oks)} | {len(oks)} |")

    lines += [
        "",
        "| Plans | With steps | Wrong | Wrong, no confirmation | "
        "Correct, extra confirmation |",
        "|---|---|---|---|---|",
    ]
    for group in ("addition", "edit", "removal"):
        rows = [r for r in results if r["group"] == group]
        wrong = [r["id"] for r in rows if r["wrong_addition"]]
        unconfirmed = [r["id"] for r in rows if r["wrong_unconfirmed"]]
        extra = [r["id"] for r in rows if r["extra_confirmation"]]
        lines.append(
            f"| {group} | {len(rows)} | {len(wrong)} {wrong} | "
            f"{len(unconfirmed)} {unconfirmed} | {len(extra)} {extra} |"
        )
    must_not = [r for r in results if r["expected"]["action"] == ["none"]]
    lines.append(
        f"\nRequests that must change nothing, with no steps: "
        f"{sum(not r['added'] for r in must_not)}/{len(must_not)}"
    )
    latencies = [r["latency_ms"] for r in results if not r["error"]]
    if latencies:
        lines.append(f"Median latency: {statistics.median(latencies):.0f} ms")
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
                if got.get("action") == "add_imagery":
                    detail.append(
                        f"time {got.get('target_date')} ±{got.get('window_days')} "
                        f"(want {exp['ranges']})"
                    )
                else:
                    detail.append(
                        f"time {got.get('start')}..{got.get('end')} "
                        f"(want {exp['ranges']})"
                    )
            elif f == "action":
                detail.append(
                    f"action {got.get('action')} (jev {got.get('jev_action')}, "
                    f"want {exp['action']})"
                )
            elif f == "confirm":
                detail.append(
                    f"confirm {got.get('needs_confirmation')} (want "
                    f"{exp['confirm']}; unclear: {r['unclear']})"
                )
            elif f == "tier":
                detail.append(f"tier {got.get('tier')} (want {exp['tier']})")
            else:
                detail.append(f"{f} {got.get(f)} (want {exp[f]})")
        if r["error"]:
            detail.append(r["error"])
        lines.append(f'- {r["id"]} "{r["prompt"]}": ' + "; ".join(detail))
    return "\n".join(lines)


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


def state_mismatch(got: dict, plan) -> list[str]:
    """The fields where `ZapPlan.state` does not agree with the state that
    the steps make. A field that the steps leave empty is not compared."""
    state = getattr(plan, "state", None)
    if state is None:
        return []
    said = state_of(state)
    return [k for k, v in got.items() if v is not None and said.get(k) != v]


async def run_case(case: dict, today: date, current=None) -> dict:
    """Plan one case. `current` replaces the fixed state of the case, for a
    follow-up that runs on the state after its first prompt."""
    from src.api.services.zap.planner import plan_zap

    sent = current or zap_current(case)
    before = state_of(sent)
    started = time.perf_counter()
    try:
        plan = await plan_zap(case["prompt"], sent, USER_ID, today=today)
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
        got = state_after(case, plan, before)
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
        "chained": current is not None,
        "sent": before,
        "sources": {
            d.question: d.source
            for d in (plan.decisions if plan else [])
            if getattr(d, "source", None)
        },
        "state_mismatch": state_mismatch(got, plan) if plan else [],
        "plan": slim_plan(plan.model_dump()) if plan else None,
    }


async def run_case_with_state(case: dict, today: date, current=None):
    """`run_case`, and the `ZapPlan.state` of the plan for the next case."""
    from src.api.services.zap.models import ZapCurrent

    result = await run_case(case, today, current)
    state = (result["plan"] or {}).get("state")
    return result, ZapCurrent(**state) if state else None


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
        f"jev model {meta['jev_model']}, extraction model "
        f"{meta.get('extract_model')}, today {meta['today']}",
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
    paths = Counter(
        f"{q}={src}"
        for r in results
        for q, src in (r.get("sources") or {}).items()
        if q in ("Area words", "Time", "Canopy cover")
    )
    if paths:
        lines.append(f"Value sources: {dict(sorted(paths.items()))}")
    mismatches = [r["id"] for r in results if r.get("state_mismatch")]
    if mismatches:
        lines.append(f"plan.state differs from the steps: {mismatches}")

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
    parser.add_argument(
        "part", choices=["dev", "test", "dashboard-dev", "dashboard-test"]
    )
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
    parser.add_argument(
        "--no-chain",
        action="store_true",
        help="Send the fixed `current` of a follow-up case, not the state "
        "after its first prompt.",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(args.env_file)

    from src.api.config import APISettings
    from src.api.services.zap import planner  # noqa: F401 - logging setup
    from src.shared.database import close_global_pool, initialize_global_pool

    _quiet_logs()

    if not APISettings.openrouter_api_key:
        sys.exit("OPENROUTER_API_KEY is not set")
    dashboard = args.part.startswith("dashboard-")
    if not dashboard and not os.environ.get("DATABASE_URL"):
        sys.exit("DATABASE_URL is not set")

    today, cases = load_part(args.part)
    if args.ids:
        cases = [c for c in cases if c["id"] in set(args.ids)]
    _fix_today(today)
    results = []
    if dashboard:
        # The dashboards are fixed: no database.
        boards = load_dashboards()
        for case in cases:
            result = await run_dashboard_case(case, today, boards)
            mark = "ok" if all(result["scores"].values()) else "FAIL"
            print(
                f"{result['id']} {mark} {result['latency_ms']} ms", flush=True
            )
            results.append(result)
    else:
        await initialize_global_pool()
        states: dict = {}
        try:
            for case in cases:
                previous = None
                if not args.no_chain and case.get("follows"):
                    previous = states.get(case["follows"])
                result, state = await run_case_with_state(
                    case, today, previous
                )
                states[case["id"]] = state
                mark = "ok" if all(result["scores"].values()) else "FAIL"
                print(
                    f"{result['id']} {mark} {result['latency_ms']} ms",
                    flush=True,
                )
                results.append(result)
        finally:
            await close_global_pool()

    meta = {
        "part": args.part,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": str(today),
        "jev_model": APISettings.jev_model,
        "extract_model": APISettings.extract_model,
        "chained": not args.no_chain,
        "git_sha": _git_sha(),
    }
    text = (dashboard_report if dashboard else report)(results, meta)
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
