"""Turn one request on a dashboard page into a plan of additions or edits,
with no agent.

Phase 4 of docs/zap-mode-plan.md (tier 1 additions) and phase 5 (layout
edits and tier 2 edits, in `edits.py`). The planner
changes nothing on the server: it returns steps, and the frontend runs each
step through a dashboard endpoint that exists. The step contract is in the
plan document ("Dashboard step contract") and in `models.py`.

Three calls start at the same time:

- Clairic call A on a dashboard (`extract_numbers`): the canopy cover and
  the cloud cover. There is no place: the area is the first area of the
  dashboard.
- Clairic call B: the time, as for the map.
- jev call 1: the `action`, the dataset, the scope, the template, and the
  jev period for when call B fails.

For `add_chart` and `add_map`, jev call 2 selects the forest type of the
dataset (and the canopy cover, when call A failed).

An edit (`add_section`, `move`, `resize`, `rename`, `change_period`,
`remove`) goes to `edits.plan_edit`, which asks jev call 2 for the target.
An action that zap does not have (delete, publish, a note) gives no steps
and a note, and so does a request for more than one area. Each decision has
a `clear` flag (`tiers.py`). A plan with a decision that is not clear is
tier 2 and needs a confirmation.
"""

import asyncio
import math
from datetime import date, timedelta
from typing import Optional

from src.api.repositories import dashboard_writer  # noqa: F401 - tests
from src.api.services.mosaic import (
    MosaicRecipe,
    MosaicResult,
    encode_recipe,
)
from src.api.services.widget_configs import dataset_config, widget_config
from src.api.services.zap import options as o
from src.api.services.zap.board import (  # noqa: F401 - re-exported
    BoardSection,
    BoardWidget,
    ZapDashboard,
    load_dashboard,
    widget_label,
)
from src.api.services.zap.edits import apply_choose, plan_edit
from src.api.services.zap.edits import decision as edit_decision
from src.api.services.zap.extract import (
    NumberExtraction,
    Range,
    TimeExtraction,
    extract_dashboard,
    snap_canopy,
)
from src.api.services.zap.jev import Answer, Question, build_state, decide
from src.api.services.zap.models import (
    ZapAddChartArgs,
    ZapAddImageryArgs,
    ZapAddMapArgs,
    ZapAddTemplateArgs,
    ZapAnalyzeBody,
    ZapAoi,
    ZapArea,
    ZapCurrent,
    ZapDecision,
    ZapMosaicQuery,
    ZapPlan,
    ZapStep,
    ZapWidgetBody,
)
from src.api.services.zap.planner import (
    CATALOG,
    CONTEXT_LABELS,
    PERIOD_THRESHOLD,
    _canopy_values,
    _context_label,
    _dataset_args,
    _decision,
    _kept_range,
    _range_label,
    _value_decision,
)
from src.api.services.zap.tiers import dashboard_tier
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# The imagery defaults. With no time in the request, the imagery is of the
# last 30 days, as the analysis templates do ("a cloud-free week is rare in
# the tropics"). A named time gives a window of half its length around its
# middle day, at least IMAGERY_MIN_WINDOW days.
IMAGERY_DEFAULT_WINDOW = 30
IMAGERY_MIN_WINDOW = 7
IMAGERY_MAX_WINDOW = 183
IMAGERY_DEFAULT_CLOUD = 20
IMAGERY_MAX_ITEMS = 50
SENTINEL2_START = date(2015, 6, 23)

NOTE_NOT_EDITABLE = (
    "Zap can edit only a dashboard that you own. Open one of your "
    "dashboards, or ask the assistant."
)
NOTE_NO_AREA = "The dashboard has no area. Add an area to the dashboard first."
NOTE_EDIT = (
    "Zap cannot delete or publish a dashboard, or write a note. Use the "
    "page controls, or ask the assistant."
)
NOTE_NONE = "Zap found nothing to add to the dashboard."
NOTE_SCOPE = (
    "A dashboard shows one area. Ask the assistant to compare areas or "
    "rank the parts of an area."
)
NOTE_NO_DATASET = "Name the data to add, for example 'tree cover loss'."
NOTE_NO_TEMPLATE = (
    "No ready-made section fits the request. The sections are: "
    + "; ".join(card.split(":")[0] for card in o.TEMPLATE_CARDS.values())
    + "."
)
NOTE_OLD_IMAGERY = (
    "Sentinel-2 imagery starts in June 2015. Zap cannot add imagery for an "
    "earlier date."
)


def _state_lines(
    dashboard: ZapDashboard, current: ZapCurrent
) -> dict[str, str]:
    lines = {
        "Name": dashboard.name,
        "Area": dashboard.area.name if dashboard.area else "not set",
        "Sections": "; ".join(dashboard.sections) or "none",
        "Widgets": "; ".join(dashboard.widgets) or "none",
    }
    if current.dataset_id in CATALOG:
        lines["Last added data"] = CATALOG[current.dataset_id]["dataset_name"]
    last_widgets = set(current.last_widget_ids or [])
    last_sections = set(current.last_section_ids or [])
    last = [
        widget_label(dashboard, w)
        for w in dashboard.widget_items
        if w.id in last_widgets
    ] + [
        f'Section "{s.title}"'
        for s in dashboard.section_items
        if s.id in last_sections
    ]
    if last:
        lines["Last edit"] = "; ".join(last)
    return lines


def _no_steps(
    current: ZapCurrent, decisions: list[ZapDecision], notes: list[str]
) -> ZapPlan:
    return ZapPlan(steps=[], decisions=decisions, notes=notes, state=current)


def _time(
    time_x, answers: dict[str, Answer], first: dict[str, Question], today: date
) -> tuple[Optional[Range], Optional[ZapDecision]]:
    """The time of the request: Clairic (or a calendar rule), else the jev
    period. None when the request names no time."""
    if isinstance(time_x, TimeExtraction):
        return time_x.range, _value_decision(
            "period",
            _range_label(time_x.range)
            if time_x.range is not None
            else "The request names no time",
            time_x.probability,
            time_x.source,
        )
    period = answers.get("period")
    if period is None:
        return None, None
    requested = None
    if period.choice != o.KEEP and period.probability >= PERIOD_THRESHOLD:
        requested = o.period_range(period.choice, today)
    return requested, _decision("period", first["period"], period)


def _imagery_window(rng: Optional[Range], today: date) -> tuple[date, int]:
    """The target date and the window (in days, each side) of the imagery
    for a time range of the request.

    - No time, or the whole record: today, IMAGERY_DEFAULT_WINDOW.
    - A range that runs to today ("recent", "the last 2 weeks", "since
      May"): the latest imagery, so today, with a window of the length of
      the range, from IMAGERY_MIN_WINDOW to IMAGERY_DEFAULT_WINDOW.
    - A range in the past: its middle day, with a window of half its
      length, from IMAGERY_MIN_WINDOW to IMAGERY_MAX_WINDOW.
    """
    if rng is None or rng == (None, None):
        return today, IMAGERY_DEFAULT_WINDOW
    start, end = rng
    last = min(date.fromisoformat(end), today) if end else today
    if start is None:
        return last, IMAGERY_DEFAULT_WINDOW
    first = date.fromisoformat(start)
    if last >= today - timedelta(days=1):
        span = (last - first).days
        return today, max(
            IMAGERY_MIN_WINDOW, min(span, IMAGERY_DEFAULT_WINDOW)
        )
    half = (last - first).days / 2
    target = first + timedelta(days=math.floor(half))
    window = max(IMAGERY_MIN_WINDOW, min(math.ceil(half), IMAGERY_MAX_WINDOW))
    return target, window


def imagery_args(
    dashboard: ZapDashboard,
    area: ZapArea,
    target: date,
    window_days: int,
    max_cloud_cover: int,
    user_id: str,
) -> ZapAddImageryArgs:
    """The mosaic request and the imagery widget. The mosaic id is the
    recipe token that the mosaic service makes for the same request, so
    the widget can name the tile URLs before the mosaic exists. A custom
    area adds the user id to the recipe, as the endpoint does for its
    caller (the owner)."""
    recipe = MosaicRecipe(
        aois=((area.source, area.src_id),),
        target_date=target,
        window_days=window_days,
        max_cloud_cover=max_cloud_cover,
        max_items=IMAGERY_MAX_ITEMS,
        user_id=user_id if area.source == "custom" else None,
    )
    mosaic = MosaicResult(mosaic_id=encode_recipe(recipe))
    snapshot = {
        "provider": "sentinel-2",
        "tile_url": mosaic.tile_url,
        "tilejson_url": mosaic.tilejson_url,
        "mosaic_id": mosaic.mosaic_id,
        "target_date": str(target),
        "window_days": window_days,
        "max_cloud_cover": max_cloud_cover,
        "aoi_names": [area.name],
    }
    return ZapAddImageryArgs(
        dashboard_id=dashboard.id,
        mosaic=ZapMosaicQuery(
            source=area.source,
            src_id=area.src_id,
            target_date=str(target),
            window_days=window_days,
            max_cloud_cover=max_cloud_cover,
            max_items=IMAGERY_MAX_ITEMS,
        ),
        widget=ZapWidgetBody(
            widget_type="map",
            config=widget_config("imagery", snapshot, None),
        ),
    )


async def plan_dashboard(
    prompt: str,
    current: ZapCurrent,
    user_id: str,
    today: date,
    dashboard: Optional[ZapDashboard] = None,
    choose: Optional[dict[str, str]] = None,
) -> ZapPlan:
    if dashboard is None:
        dashboard = await load_dashboard(current.dashboard_id, user_id)
    if dashboard is None:
        return _no_steps(current, [], [NOTE_NOT_EDITABLE])
    area = dashboard.area
    if area is None or not area.subtype:
        return _no_steps(current, [], [NOTE_NO_AREA])
    current = current.model_copy(
        update={"page": "dashboard", "dashboard_id": dashboard.id}
    )

    state = build_state(
        prompt, _state_lines(dashboard, current), str(today), "dashboard"
    )
    kept_dataset = (
        CATALOG[current.dataset_id]["dataset_name"]
        if current.dataset_id in o.DATASET_CARDS
        else None
    )
    first = {
        "action": Question(o.ACTION_INSTRUCTIONS, o.ACTIONS),
        "dataset": Question(
            o.DATASET_INSTRUCTIONS,
            {
                **{str(i): card for i, card in o.DATASET_CARDS.items()},
                o.KEEP: f"Keep the last added data ({kept_dataset})"
                if kept_dataset
                else "The request names no data",
            },
        ),
        "scope": Question(o.SCOPE_INSTRUCTIONS, o.SCOPES),
        "template": Question(
            o.TEMPLATE_INSTRUCTIONS,
            {**o.TEMPLATE_CARDS, o.NONE: "No ready-made section fits"},
        ),
        "period": Question(
            o.PERIOD_INSTRUCTIONS,
            {
                **o.period_options(today),
                o.KEEP: "The request names no time",
            },
        ),
    }
    (numbers_x, time_x), answers = await asyncio.gather(
        extract_dashboard(prompt, today), decide(state, first)
    )
    clairic_numbers = isinstance(numbers_x, NumberExtraction)
    clairic_time = isinstance(time_x, TimeExtraction)
    if not clairic_numbers:
        logger.warning("zap_clairic_numbers_failed", error=str(numbers_x))
    if not clairic_time:
        logger.warning("zap_clairic_time_failed", error=str(time_x))

    decisions: list[ZapDecision] = []
    chosen = apply_choose(answers, first, choose)
    action_answer = answers.get("action")
    action = action_answer.choice if action_answer else o.NONE
    if action_answer:
        decisions.append(
            edit_decision(
                "action",
                first["action"],
                action_answer,
                chosen="action" in chosen,
            )
        )
    # The decisions that the plan depends on, for the tier.
    used: list[ZapDecision] = list(decisions)

    requested: Optional[Range] = None
    if action in o.EDIT_ACTIONS:
        if action == "change_period":
            requested, time_decision = _time(time_x, answers, first, today)
            if time_decision:
                decisions.append(time_decision)
                used.append(time_decision)
        return await plan_edit(
            action,
            dashboard,
            area,
            current,
            state,
            decide,
            numbers_x if isinstance(numbers_x, NumberExtraction) else None,
            requested,
            decisions,
            used,
            choose,
            today,
        )
    if action not in o.ADD_ACTIONS:
        return _no_steps(
            current, decisions, [NOTE_EDIT if action == "edit" else NOTE_NONE]
        )
    scope = answers["scope"].choice if "scope" in answers else "single"
    if scope != "single":
        decisions.append(_decision("scope", first["scope"], answers["scope"]))
        return _no_steps(current, decisions, [NOTE_SCOPE])

    # The time: Clairic (or a calendar rule), else the jev period.
    if action != "add_template":
        requested, time_decision = _time(time_x, answers, first, today)
        if time_decision:
            decisions.append(time_decision)
            used.append(time_decision)

    notes: list[str] = []
    if action == "add_template":
        return _template_plan(
            dashboard, current, first, answers, decisions, used
        )
    if action == "add_imagery":
        return _imagery_plan(
            dashboard,
            area,
            current,
            requested,
            numbers_x if isinstance(numbers_x, NumberExtraction) else None,
            decisions,
            used,
            notes,
            user_id,
            today,
        )

    # add_chart and add_map: the dataset, then jev call 2 for its options.
    dataset_answer = answers.get("dataset")
    new_dataset = (
        int(dataset_answer.choice)
        if dataset_answer and dataset_answer.choice.isdigit()
        else None
    )
    if dataset_answer:
        dataset_decision = _decision(
            "dataset", first["dataset"], dataset_answer
        )
        decisions.append(dataset_decision)
        used.append(dataset_decision)
    dataset_id = new_dataset or (
        current.dataset_id if current.dataset_id in o.DATASET_CARDS else None
    )
    if dataset_id is None:
        return _no_steps(current, decisions, [NOTE_NO_DATASET])
    ds = CATALOG[dataset_id]

    second: dict[str, Question] = {}
    layers = [layer["value"] for layer in ds.get("context_layers") or []]
    kept_context = (
        current.context_layer
        if current.context_layer in layers and dataset_id == current.dataset_id
        else None
    )
    if layers:
        context_options = {
            value: CONTEXT_LABELS.get(value, value) for value in layers
        }
        if kept_context:
            context_options[o.KEEP] = (
                "The request names no forest type: keep the last one "
                f"({_context_label(kept_context)})"
            )
        context_options[o.NONE] = "All tree cover, no forest type filter"
        second["context"] = Question(
            o.CONTEXT_KEEP_INSTRUCTIONS
            if kept_context
            else o.CONTEXT_INSTRUCTIONS,
            context_options,
        )
    canopy_values = _canopy_values(ds)
    if canopy_values and not clairic_numbers:
        second["canopy"] = Question(
            o.CANOPY_INSTRUCTIONS,
            {
                **{
                    str(v): f"At least {v}% canopy cover"
                    for v in canopy_values
                },
                o.NONE: "No threshold named (keep the current one)",
            },
        )
    later: dict[str, Answer] = {}
    if second:
        later = await decide(state, second)
        later = {k: v for k, v in later.items() if k in second}
    for name, answer in later.items():
        decision = _decision(name, second[name], answer)
        decisions.append(decision)
        used.append(decision)

    context_layer: Optional[str] = None
    if "context" in later:
        choice = later["context"].choice
        if choice == o.KEEP:
            context_layer = kept_context
        elif choice != o.NONE:
            context_layer = choice

    canopy_cover: Optional[int] = (
        current.canopy_cover
        if canopy_values
        and current.canopy_cover in canopy_values
        and dataset_id == current.dataset_id
        else None
    )
    if clairic_numbers:
        assert isinstance(numbers_x, NumberExtraction)
        if numbers_x.canopy is not None and canopy_values:
            canopy_cover, note = snap_canopy(numbers_x.canopy, canopy_values)
            if note:
                notes.append(note)
            decision = _value_decision(
                "canopy",
                f"At least {canopy_cover}% canopy cover",
                numbers_x.canopy_probability,
                "clairic",
            )
            decisions.append(decision)
            used.append(decision)
    elif "canopy" in later and later["canopy"].choice.isdigit():
        canopy_cover = int(later["canopy"].choice)

    start, end = (
        requested
        if requested is not None
        else (
            await _kept_range(current)
            if dataset_id == current.dataset_id
            else (None, None)
        )
    )
    result = await _dataset_args(
        dataset_id, start, end, context_layer, canopy_cover
    )
    dates = (str(result.start_date), str(result.end_date))
    detail = [f"{dates[0][:4]}–{dates[1][:4]}"]
    if context_layer:
        detail.append(context_layer.replace("_", " "))
    if canopy_cover is not None:
        detail.append(f"≥{canopy_cover}% canopy")
    detail.append(area.name)

    if action == "add_chart":
        step = ZapStep(
            kind="add_chart",
            title=f"Add chart: {result.dataset_name}",
            detail=" · ".join(detail),
            args=ZapAddChartArgs(
                dashboard_id=dashboard.id,
                dataset_name=result.dataset_name,
                analyze=ZapAnalyzeBody(
                    aois=[
                        ZapAoi(
                            source=area.source,
                            src_id=area.src_id,
                            subtype=area.subtype,
                        )
                    ],
                    dataset_id=dataset_id,
                    start_date=dates[0],
                    end_date=dates[1],
                    context_layer=context_layer,
                    canopy_cover=canopy_cover,
                ),
                widget=ZapWidgetBody(
                    widget_type="insight", config={"default_view": "chart"}
                ),
            ).model_dump(),
        )
    else:
        snapshot = dataset_config({"dataset": result.model_dump()})
        if snapshot is None:
            return _no_steps(
                current,
                decisions,
                [f"{result.dataset_name} has no map layer to add."],
            )
        step = ZapStep(
            kind="add_map",
            title=f"Add map: {result.dataset_name}",
            detail=" · ".join(detail),
            args=ZapAddMapArgs(
                dashboard_id=dashboard.id,
                dataset_name=result.dataset_name,
                widget=ZapWidgetBody(
                    widget_type="map",
                    config=widget_config("dataset", snapshot, None),
                ),
            ).model_dump(),
        )

    tier = dashboard_tier(d.clear for d in used)
    after = current.model_copy(
        update={
            "area": area,
            "dataset_id": dataset_id,
            "start_date": dates[0],
            "end_date": dates[1],
            "context_layer": result.context_layer,
            "canopy_cover": canopy_cover,
        }
    )
    return ZapPlan(
        steps=[step],
        decisions=decisions,
        notes=notes,
        state=after,
        tier=tier,
        needs_confirmation=tier >= 2,
    )


def _template_plan(
    dashboard: ZapDashboard,
    current: ZapCurrent,
    first: dict[str, Question],
    answers: dict[str, Answer],
    decisions: list[ZapDecision],
    used: list[ZapDecision],
) -> ZapPlan:
    answer = answers.get("template")
    if answer:
        decision = _decision("template", first["template"], answer)
        decisions.append(decision)
        used.append(decision)
    if answer is None or answer.choice not in o.TEMPLATE_CARDS:
        return _no_steps(current, decisions, [NOTE_NO_TEMPLATE])
    card = o.TEMPLATE_CARDS[answer.choice]
    title, _, detail = card.partition(": ")
    tier = dashboard_tier(d.clear for d in used)
    return ZapPlan(
        steps=[
            ZapStep(
                kind="add_template",
                title=f"Add section: {title}",
                detail=detail,
                args=ZapAddTemplateArgs(
                    dashboard_id=dashboard.id, template=answer.choice
                ).model_dump(),
            )
        ],
        decisions=decisions,
        notes=[],
        state=current.model_copy(update={"area": dashboard.area}),
        tier=tier,
        needs_confirmation=tier >= 2,
    )


def _imagery_plan(
    dashboard: ZapDashboard,
    area: ZapArea,
    current: ZapCurrent,
    requested: Optional[Range],
    numbers: Optional[NumberExtraction],
    decisions: list[ZapDecision],
    used: list[ZapDecision],
    notes: list[str],
    user_id: str,
    today: date,
) -> ZapPlan:
    target, window = _imagery_window(requested, today)
    if target + timedelta(days=window) < SENTINEL2_START:
        return _no_steps(current, decisions, [NOTE_OLD_IMAGERY])
    cloud = IMAGERY_DEFAULT_CLOUD
    if numbers is not None and numbers.cloud is not None:
        cloud = max(1, min(round(numbers.cloud), 100))
        decision = _value_decision(
            "cloud",
            f"At most {cloud}% cloud cover",
            numbers.cloud_probability,
            "clairic",
        )
        decisions.append(decision)
        used.append(decision)
    args = imagery_args(dashboard, area, target, window, cloud, user_id)
    tier = dashboard_tier(d.clear for d in used)
    return ZapPlan(
        steps=[
            ZapStep(
                kind="add_imagery",
                title="Add imagery: Sentinel-2",
                detail=(
                    f"around {target} · ±{window} days · ≤{cloud}% clouds"
                    f" · {area.name}"
                ),
                args=args.model_dump(),
            )
        ],
        decisions=decisions,
        notes=notes,
        state=current.model_copy(update={"area": area}),
        tier=tier,
        needs_confirmation=tier >= 2,
    )
