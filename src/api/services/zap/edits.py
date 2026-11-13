"""The layout edits and the tier 2 edits of zap on a dashboard (phase 5 of
docs/zap-mode-plan.md): `add_section`, `move`, `resize`, `rename`,
`change_period` and `remove`.

The planner changes nothing on the server. Each edit is one step with
typed args for a dashboard endpoint that exists, and the frontend runs it
with no lookup. The step contract is in the plan document ("Dashboard step
contract").

jev call 1 (in `dashboard.py`) selects the action. For an edit with a
target, jev call 2 asks the `target` question: the options are the widgets
and the sections of the dashboard (and the dashboard itself for a rename),
each with a readable label, and "none of these". The items of the last edit
(`current.last_widget_ids`, `current.last_section_ids`) come first and are
marked, so that "remove that" selects them. Call 2 also asks the
destination of a move, the width of a resize, and what happens to the
widgets of a removed section. The new name of `rename` and `add_section` is
the `title` field of Clairic: the words of the user. Zap writes no text.

A target that jev does not find gives no steps and a note. `change_period`
and `remove` always need a confirmation (`tiers.ALWAYS_CONFIRM`).
"""

from dataclasses import dataclass
from datetime import date
from typing import Awaitable, Callable, Literal, Optional

from src.api.services.widget_configs import dataset_config, widget_config
from src.api.services.zap import options as o
from src.api.services.zap.board import (
    SIZE_LABELS,
    BoardSection,
    BoardWidget,
    ZapDashboard,
    section_label,
    widget_label,
)
from src.api.services.zap.extract import NumberExtraction, Range
from src.api.services.zap.jev import Answer, Question
from src.api.services.zap.models import (
    ZapAddSectionArgs,
    ZapAnalyzeBody,
    ZapAoi,
    ZapArea,
    ZapChangePeriodArgs,
    ZapCurrent,
    ZapDecision,
    ZapDecisionOption,
    ZapMoveArgs,
    ZapPlacedWidgetBody,
    ZapPlan,
    ZapRemoveArgs,
    ZapRenameArgs,
    ZapResizeArgs,
    ZapStep,
)
from src.api.services.zap.planner import (
    CATALOG,
    QUESTION_LABELS,
    _dataset_args,
    _option_label,
)
from src.api.services.zap.tiers import (
    TOP_OPTIONS,
    clairic_clear,
    dashboard_tier,
    jev_clear,
)

# Set to False to keep the old widget of `change_period` and add the new
# widget next to it (open decision 2 of the plan document).
CHANGE_PERIOD_REPLACES = True

LAST_EDIT = "The last edit: "

NOTE_NO_TITLE = (
    "Write the new name in the request, for example 'rename the section to "
    "Fire season'. Zap does not make up names."
)
NOTE_NO_TARGET = (
    "Zap found no widget or section on the dashboard that fits the "
    "request. Nothing changed."
)
NOTE_NO_DESTINATION = (
    "Zap found no place to move the widget to. Name a section of the "
    "dashboard, or 'the top level'."
)
NOTE_NO_PERIOD = (
    "Name the new period, for example 'since 2015' or 'March 2026'."
)
NOTE_NO_ANALYSIS = (
    "Zap can change the period of a chart or a dataset map that it can "
    "build again. Ask the assistant for this widget."
)
NOTE_NOTHING = {
    "move": "The dashboard has no widget to move.",
    "resize": "The dashboard has no widget to resize.",
    "change_period": "The dashboard has no chart or map to change.",
    "remove": "The dashboard has no widget or section to remove.",
}
NOTE_NO_SECTIONS = (
    "The dashboard has no section to move the widget to. Add a section "
    "first, for example 'add a section called Fires'."
)

Ask = Callable[[str, dict[str, Question]], Awaitable[dict[str, Answer]]]


@dataclass
class Target:
    key: str  # the jev option key, e.g. "w1"
    value: str  # the option id, e.g. "widget:<id>", "section:<id>"
    label: str  # the readable label, with no last-edit mark
    widget: Optional[BoardWidget] = None
    section: Optional[BoardSection] = None
    last: bool = False

    @property
    def option(self) -> str:
        return f"{LAST_EDIT}{self.label}" if self.last else self.label


def targets(
    board: ZapDashboard, action: str, current: ZapCurrent
) -> list[Target]:
    """The targets of an action, the items of the last edit first."""
    last_widgets = set(current.last_widget_ids or [])
    last_sections = set(current.last_section_ids or [])
    found: list[Target] = []
    if action in ("move", "resize", "change_period", "remove"):
        for i, w in enumerate(board.widget_items):
            if action == "change_period" and w.analysis is None:
                continue
            found.append(
                Target(
                    key=f"w{i + 1}",
                    value=f"widget:{w.id}",
                    label=widget_label(board, w),
                    widget=w,
                    last=w.id in last_widgets,
                )
            )
    if action == "rename":
        found.append(
            Target(
                key="dashboard",
                value="dashboard",
                label=f'The dashboard name "{board.name}"',
            )
        )
    if action in ("rename", "remove"):
        for i, s in enumerate(board.section_items):
            found.append(
                Target(
                    key=f"s{i + 1}",
                    value=f"section:{s.id}",
                    label=section_label(board, s),
                    section=s,
                    last=s.id in last_sections,
                )
            )
    # A stable sort keeps the dashboard order in each group.
    return sorted(found, key=lambda t: not t.last)


def apply_choose(
    answers: dict[str, Answer],
    questions: dict[str, Question],
    choose: Optional[dict[str, str]],
    values: Optional[dict[str, dict[str, str]]] = None,
) -> set[str]:
    """Replace the jev answers with the options that the user selected.
    `values` maps the option keys of a question to their ids. Return the
    names of the questions that the user answered."""
    chosen: set[str] = set()
    for name, value in (choose or {}).items():
        if name not in questions:
            continue
        by_value = {v: k for k, v in (values or {}).get(name, {}).items()}
        key = by_value.get(value, value)
        if key not in questions[name].options:
            continue
        answers[name] = Answer(
            choice=key, probability=1.0, probabilities={key: 1.0}
        )
        chosen.add(name)
    return chosen


def decision(
    name: str,
    question: Question,
    answer: Answer,
    values: Optional[dict[str, str]] = None,
    chosen: bool = False,
) -> ZapDecision:
    """A jev decision with its key and option ids, so that the frontend
    can send a selected option back in `choose`. The other options are the
    next options, best first, with no "none" option."""
    values = values or {}
    ranked = sorted(
        (
            (option, p)
            for option, p in answer.probabilities.items()
            if option != answer.choice
            and option in question.options
            and option not in (o.KEEP, o.NONE)
            and p > 0
        ),
        key=lambda item: -item[1],
    )
    return ZapDecision(
        question=QUESTION_LABELS[name],
        label=_option_label(name, question, answer.choice),
        probability=round(answer.probability, 3),
        source="user" if chosen else "jev",
        options=[
            ZapDecisionOption(
                label=_option_label(name, question, option),
                probability=round(p, 3),
                value=values.get(option, option),
            )
            for option, p in ranked[:TOP_OPTIONS]
        ],
        clear=True
        if chosen
        else jev_clear(answer.choice, answer.probabilities),
        key=name,
        value=values.get(answer.choice, answer.choice),
    )


def _no_steps(
    current: ZapCurrent, decisions: list[ZapDecision], notes: list[str]
) -> ZapPlan:
    return ZapPlan(steps=[], decisions=decisions, notes=notes, state=current)


def _plan(
    step: ZapStep,
    action: str,
    used: list[ZapDecision],
    decisions: list[ZapDecision],
    notes: list[str],
    state: ZapCurrent,
    changed_widgets: int,
) -> ZapPlan:
    tier = dashboard_tier((d.clear for d in used), action, changed_widgets)
    return ZapPlan(
        steps=[step],
        decisions=decisions,
        notes=notes,
        state=state,
        tier=tier,
        needs_confirmation=tier >= 2,
    )


def _title_decision(numbers: Optional[NumberExtraction]) -> ZapDecision:
    title = numbers.title if numbers else None
    probability = numbers.title_probability if numbers else 0.0
    return ZapDecision(
        question=QUESTION_LABELS["title"],
        label=f'"{title}"' if title else "No new name in the request",
        probability=round(probability if title else 1 - probability, 3),
        source="clairic",
        clear=clairic_clear(probability) if title else False,
    )


def _years(start: Optional[str], end: Optional[str]) -> str:
    if not start or not end:
        return "all years"
    if start[:4] == end[:4]:
        return start[:7] if start[5:7] == end[5:7] else start[:4]
    return f"{start[:4]}–{end[:4]}"


async def plan_edit(
    action: str,
    board: ZapDashboard,
    area: ZapArea,
    current: ZapCurrent,
    state_text: str,
    ask: Ask,
    numbers: Optional[NumberExtraction],
    requested: Optional[Range],
    decisions: list[ZapDecision],
    used: list[ZapDecision],
    choose: Optional[dict[str, str]],
    today: date,
) -> ZapPlan:
    """The plan of one edit. `decisions` and `used` already hold the
    action decision (and the time decision for `change_period`)."""
    # The state after an edit: the frontend sets the ids of the new items.
    after = current.model_copy(
        update={
            "area": area,
            "last_widget_ids": None,
            "last_section_ids": None,
        }
    )

    if action == "add_section":
        title = _title_decision(numbers)
        decisions.append(title)
        used.append(title)
        if not numbers or not numbers.title:
            return _no_steps(current, decisions, [NOTE_NO_TITLE])
        step = ZapStep(
            kind="add_section",
            title=f'Add section: "{numbers.title}"',
            detail="an empty section",
            args=ZapAddSectionArgs(
                dashboard_id=board.id, section={"title": numbers.title}
            ).model_dump(),
        )
        return _plan(step, action, used, decisions, [], after, 0)

    # Checks that need no jev call.
    if action == "rename":
        title = _title_decision(numbers)
        decisions.append(title)
        used.append(title)
        if not numbers or not numbers.title:
            return _no_steps(current, decisions, [NOTE_NO_TITLE])
    if action == "change_period" and requested is None:
        return _no_steps(current, decisions, [NOTE_NO_PERIOD])
    found = targets(board, action, current)
    if not found:
        return _no_steps(
            current,
            decisions,
            [
                NOTE_NO_ANALYSIS
                if action == "change_period" and board.widget_items
                else NOTE_NOTHING.get(action, NOTE_NO_TARGET)
            ],
        )
    if action == "move" and not board.section_items:
        if all(t.widget and t.widget.section_id is None for t in found):
            return _no_steps(current, decisions, [NOTE_NO_SECTIONS])

    # jev call 2: the target, and the other choices of the action.
    by_key = {t.key: t for t in found}
    second: dict[str, Question] = {
        "target": Question(
            o.TARGET_INSTRUCTIONS[action] + o.TARGET_RULES,
            {**{t.key: t.option for t in found}, o.NONE: o.TARGET_NONE},
        )
    }
    values: dict[str, dict[str, str]] = {
        "target": {t.key: t.value for t in found}
    }
    if action == "move":
        second["destination"] = Question(
            o.DESTINATION_INSTRUCTIONS,
            {
                **{
                    f"s{i + 1}": f'Section "{s.title}"'
                    for i, s in enumerate(board.section_items)
                },
                "top": o.DESTINATION_TOP,
                o.NONE: "A place that is not on the dashboard",
            },
        )
        values["destination"] = {
            f"s{i + 1}": f"section:{s.id}"
            for i, s in enumerate(board.section_items)
        }
    if action == "resize":
        second["size"] = Question(o.SIZE_INSTRUCTIONS, dict(o.SIZES))
    if action == "remove" and board.section_items:
        second["widgets"] = Question(
            o.WIDGETS_INSTRUCTIONS, dict(o.WIDGETS_CHOICES)
        )
    answers = await ask(state_text, second)
    answers = {k: v for k, v in answers.items() if k in second}
    chosen = apply_choose(answers, second, choose, values)

    target_answer = answers.get("target")
    if target_answer is None:
        return _no_steps(current, decisions, [NOTE_NO_TARGET])
    target_decision = decision(
        "target",
        second["target"],
        target_answer,
        values["target"],
        "target" in chosen,
    )
    decisions.append(target_decision)
    used.append(target_decision)
    target = by_key.get(target_answer.choice)
    if target is None:
        return _no_steps(current, decisions, [NOTE_NO_TARGET])

    def extra(name: str) -> Optional[Answer]:
        answer = answers.get(name)
        if answer is not None:
            d = decision(
                name, second[name], answer, values.get(name), name in chosen
            )
            decisions.append(d)
            used.append(d)
        return answer

    if action == "move":
        assert target.widget is not None
        return _move(
            board,
            target,
            extra("destination"),
            current,
            after,
            decisions,
            used,
        )
    if action == "resize":
        assert target.widget is not None
        return _resize(
            board, target, extra("size"), current, after, decisions, used
        )
    if action == "rename":
        assert numbers is not None and numbers.title
        return _rename(
            board, target, numbers.title, current, after, decisions, used
        )
    if action == "change_period":
        assert target.widget is not None and requested is not None
        return await _change_period(
            board, area, target, requested, current, after, decisions, used
        )
    # remove
    widgets_answer = extra("widgets") if target.section else None
    return _remove(board, target, widgets_answer, after, decisions, used)


def _move(board, target, answer, current, after, decisions, used) -> ZapPlan:
    widget: BoardWidget = target.widget
    if answer is None or answer.choice == o.NONE:
        return _no_steps(current, decisions, [NOTE_NO_DESTINATION])
    if answer.choice == "top":
        section = None
    else:
        section = board.section_items[int(answer.choice[1:]) - 1]
    section_id = section.id if section else None
    where = f'section "{section.title}"' if section else "the top level"
    if widget.section_id == section_id:
        return _no_steps(
            current,
            decisions,
            [f'{widget.kind} "{widget.title}" is already in {where}.'],
        )
    step = ZapStep(
        kind="move",
        title=f'Move: {widget.kind} "{widget.title}"',
        detail=f"to {where}",
        args=ZapMoveArgs(
            dashboard_id=board.id,
            widget_id=widget.id,
            widget_label=target.label,
            destination_label=where,
            patch={"section_id": section_id},
        ).model_dump(),
    )
    state = after.model_copy(update={"last_widget_ids": [widget.id]})
    return _plan(step, "move", used, decisions, [], state, 1)


def _resize(board, target, answer, current, after, decisions, used) -> ZapPlan:
    widget: BoardWidget = target.widget
    if answer is None or answer.choice not in SIZE_LABELS:
        return _no_steps(current, decisions, [NOTE_NO_TARGET])
    size = answer.choice
    if widget.size == size:
        return _no_steps(
            current,
            decisions,
            [
                f'{widget.kind} "{widget.title}" is already '
                f"{SIZE_LABELS[size]}."
            ],
        )
    step = ZapStep(
        kind="resize",
        title=f'Resize: {widget.kind} "{widget.title}"',
        detail=f"{SIZE_LABELS[size]} (was {SIZE_LABELS[widget.size]})",
        args=ZapResizeArgs(
            dashboard_id=board.id,
            widget_id=widget.id,
            widget_label=target.label,
            size=size,
            patch={"config": {**widget.config, "size": size}},
        ).model_dump(),
    )
    state = after.model_copy(update={"last_widget_ids": [widget.id]})
    return _plan(step, "resize", used, decisions, [], state, 1)


def _rename(board, target, title, current, after, decisions, used) -> ZapPlan:
    target_type: Literal["dashboard", "section"]
    section_id: Optional[str]
    if target.section is None:
        old, target_type, section_id = board.name, "dashboard", None
        patch = {"name": title}
    else:
        old, target_type = target.section.title, "section"
        section_id = target.section.id
        patch = {"title": title}
    noun = target_type
    if old == title:
        return _no_steps(
            current, decisions, [f'The {noun} is already named "{title}".']
        )
    step = ZapStep(
        kind="rename",
        title=f'Rename {noun}: "{old}"',
        detail=f'to "{title}"',
        args=ZapRenameArgs(
            dashboard_id=board.id,
            target_type=target_type,
            section_id=section_id,
            old_title=old,
            title=title,
            patch=patch,
        ).model_dump(),
    )
    state = after.model_copy(
        update={"last_section_ids": [section_id] if section_id else None}
    )
    return _plan(step, "rename", used, decisions, [], state, 0)


# The config keys of a widget that a new period keeps. The others refer to
# the old charts (`chartIds`, `titles`) or to the old period (`title`).
KEPT_CONFIG = ("size", "default_view", "viewport")


async def _change_period(
    board, area, target, requested, current, after, decisions, used
) -> ZapPlan:
    widget: BoardWidget = target.widget
    analysis = widget.analysis or {}
    dataset_id = analysis.get("dataset_id")
    if not isinstance(dataset_id, int) or dataset_id not in CATALOG:
        return _no_steps(current, decisions, [NOTE_NO_ANALYSIS])
    context_layer = analysis.get("context_layer")
    canopy_cover = analysis.get("canopy_cover")
    result = await _dataset_args(
        dataset_id, requested[0], requested[1], context_layer, canopy_cover
    )
    dates = (str(result.start_date), str(result.end_date))
    old = (analysis.get("start_date"), analysis.get("end_date"))
    if dates == old:
        return _no_steps(
            current,
            decisions,
            [
                f'{widget.kind} "{widget.title}" already shows '
                f"{dates[0]} to {dates[1]}."
            ],
        )
    kept = {k: widget.config[k] for k in KEPT_CONFIG if k in widget.config}
    widget_type: Literal["insight", "map"]
    analyze = None
    if widget.widget_type == "insight":
        analyze = ZapAnalyzeBody(
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
        )
        config = {"default_view": "chart", **kept}
        widget_type = "insight"
    else:
        snapshot = dataset_config({"dataset": result.model_dump()})
        if snapshot is None:
            return _no_steps(current, decisions, [NOTE_NO_ANALYSIS])
        config = {**widget_config("dataset", snapshot, None), **kept}
        widget_type = "map"
    step = ZapStep(
        kind="change_period",
        title=f'New period: {widget.kind} "{widget.title}"',
        detail=(
            f"{_years(*dates)} (was {_years(*old)}) · "
            + (
                "replaces the widget"
                if CHANGE_PERIOD_REPLACES
                else "a new widget next to it"
            )
        ),
        args=ZapChangePeriodArgs(
            dashboard_id=board.id,
            widget_id=widget.id,
            widget_label=target.label,
            dataset_name=result.dataset_name,
            old_start_date=old[0],
            old_end_date=old[1],
            replace=CHANGE_PERIOD_REPLACES,
            analyze=analyze,
            widget=ZapPlacedWidgetBody(
                widget_type=widget_type,
                config=config,
                position=widget.position,
                section_id=widget.section_id,
            ),
        ).model_dump(),
    )
    state = after.model_copy(
        update={
            "dataset_id": dataset_id,
            "start_date": dates[0],
            "end_date": dates[1],
            "context_layer": result.context_layer,
            "canopy_cover": canopy_cover,
        }
    )
    return _plan(step, "change_period", used, decisions, [], state, 1)


def _remove(board, target, widgets_answer, after, decisions, used) -> ZapPlan:
    if target.widget is not None:
        widget = target.widget
        step = ZapStep(
            kind="remove",
            title=f'Remove: {widget.kind} "{widget.title}"',
            detail="the widget only; its insight stays",
            args=ZapRemoveArgs(
                dashboard_id=board.id,
                target_type="widget",
                widget_id=widget.id,
                label=target.label,
            ).model_dump(),
        )
        return _plan(step, "remove", used, decisions, [], after, 1)
    section = target.section
    inside = board.widgets_of(section.id)
    delete = bool(widgets_answer and widgets_answer.choice == "with_widgets")
    labels = [widget_label(board, w) for w in inside]
    count = len(inside)
    noun = "widget" if count == 1 else "widgets"
    if not inside:
        detail = "an empty section"
    elif delete:
        detail = f"and its {count} {noun}"
    else:
        verb = "moves" if count == 1 else "move"
        detail = f"its {count} {noun} {verb} to the top level"
    step = ZapStep(
        kind="remove",
        title=f'Remove section: "{section.title}"',
        detail=detail,
        args=ZapRemoveArgs(
            dashboard_id=board.id,
            target_type="section",
            section_id=section.id,
            label=target.label,
            delete_widgets=delete,
            widget_labels=labels,
        ).model_dump(),
    )
    return _plan(
        step, "remove", used, decisions, [], after, count if delete else 0
    )
