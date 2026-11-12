"""Tests for the zap edits on a dashboard page (phase 5): add_section,
move, resize, rename, change_period and remove, with jev and Clairic
mocked."""

from datetime import date

import pytest

from src.api.services.zap import dashboard as zd
from src.api.services.zap import edits, planner
from src.api.services.zap import options as o
from src.api.services.zap.board import BoardSection, BoardWidget
from src.api.services.zap.extract import (
    ExtractError,
    NumberExtraction,
    TimeExtraction,
)
from src.api.services.zap.jev import Answer
from src.api.services.zap.models import ZapArea, ZapCurrent
from src.api.services.zap.tiers import dashboard_tier

TODAY = date(2026, 11, 12)
PARA = ZapArea(
    name="Pará, Brazil",
    source="gadm",
    src_id="BRA.14_1",
    subtype="state-province",
)
OVERVIEW = BoardSection(id="sec-overview", title="Overview", position=0)
FIRES = BoardSection(id="sec-fires", title="Fires", position=1)
LOSS_CHART = BoardWidget(
    id="w-loss",
    widget_type="insight",
    title="Tree cover loss per year",
    kind="Chart",
    position=0,
    section_id=OVERVIEW.id,
    config={"default_view": "chart", "chartIds": ["c1"], "size": "single"},
    insight_id="i-loss",
    analysis={
        "dataset_id": 4,
        "start_date": "2001-01-01",
        "end_date": "2025-12-31",
        "context_layer": "primary_forest",
        "canopy_cover": 30,
    },
)
LOSS_MAP = BoardWidget(
    id="w-map",
    widget_type="map",
    title="Tree cover loss",
    kind="Map",
    position=0,
    section_id=None,
    config={"default_view": "map", "dataset": {"dataset_id": 4}},
    analysis={
        "dataset_id": 4,
        "start_date": "2001-01-01",
        "end_date": "2025-12-31",
        "context_layer": None,
        "canopy_cover": None,
    },
)
FIRE_CHART = BoardWidget(
    id="w-fire",
    widget_type="insight",
    title="Tree cover loss due to fires",
    kind="Chart",
    position=0,
    section_id=FIRES.id,
    insight_id="i-fire",
    analysis={
        "dataset_id": 10,
        "start_date": "2001-01-01",
        "end_date": "2025-12-31",
        "context_layer": None,
        "canopy_cover": None,
    },
)
IMAGERY = BoardWidget(
    id="w-img",
    widget_type="map",
    title="Sentinel-2 imagery",
    kind="Imagery",
    position=1,
    section_id=None,
    config={"default_view": "map", "imagery": {"mosaic_id": "m"}},
)
BOARD = zd.ZapDashboard(
    id="5b0c4f9e-0000-4000-8000-000000000001",
    name="Pará forest",
    area=PARA,
    section_items=[OVERVIEW, FIRES],
    widget_items=[LOSS_CHART, LOSS_MAP, FIRE_CHART, IMAGERY],
)
PAGE = ZapCurrent(page="dashboard", dashboard_id=BOARD.id)


def _answer(choice, p=0.9, **others):
    return Answer(
        choice=choice, probability=p, probabilities={choice: p, **others}
    )


def _round(**choices):
    return {
        name: value if isinstance(value, Answer) else _answer(value)
        for name, value in choices.items()
    }


def _first(action):
    return _round(
        action=action,
        dataset=o.KEEP,
        template=o.NONE,
        scope="single",
        period=o.KEEP,
    )


@pytest.fixture
def jev(monkeypatch):
    calls = []

    def install(*rounds):
        queue = list(rounds)

        async def fake_decide(state, questions):
            calls.append((state, questions))
            return queue.pop(0)

        monkeypatch.setattr(zd, "decide", fake_decide)
        return calls

    return install


@pytest.fixture
def clairic(monkeypatch):
    def install(title=None, title_p=0.97, time=None, fail=False):
        numbers = (
            ExtractError("no answer")
            if fail
            else NumberExtraction(
                canopy=None,
                canopy_probability=0.03,
                cloud=None,
                cloud_probability=0.03,
                title=title,
                title_probability=title_p if title else 0.02,
            )
        )
        time_x = TimeExtraction(
            when="words" if time else None,
            range=time,
            source="code",
            probability=0.98,
        )

        async def fake_extract(prompt, today):
            return numbers, time_x

        monkeypatch.setattr(zd, "extract_dashboard", fake_extract)

    install()
    return install


async def _plan(prompt, current=PAGE, choose=None):
    return await planner.plan_zap(
        prompt, current, "owner", TODAY, dashboard=BOARD, choose=choose
    )


def _target_options(calls):
    return calls[-1][1]["target"].options


# --- add_section --------------------------------------------------------------


async def test_add_section_uses_the_words_of_the_user(jev, clairic):
    calls = jev(_first("add_section"))
    clairic(title="Fire season")

    plan = await _plan("add a section called Fire season")

    assert [s.kind for s in plan.steps] == ["add_section"]
    assert plan.steps[0].args == {
        "dashboard_id": BOARD.id,
        "section": {"title": "Fire season"},
    }
    assert plan.tier == 1
    assert plan.needs_confirmation is False
    # No target question.
    assert len(calls) == 1


async def test_add_section_with_no_title_adds_nothing(jev, clairic):
    jev(_first("add_section"))
    clairic(title=None)

    plan = await _plan("add a section")

    assert plan.steps == []
    assert plan.notes == [edits.NOTE_NO_TITLE]


async def test_add_section_with_a_title_that_is_not_clear_needs_a_confirmation(
    jev, clairic
):
    jev(_first("add_section"))
    clairic(title="Fires", title_p=0.6)

    plan = await _plan("add a section Fires")

    assert plan.tier == 2
    assert plan.needs_confirmation is True


# --- The target question -------------------------------------------------------


async def test_target_options_are_the_widgets_with_labels(jev, clairic):
    calls = jev(_first("resize"), _round(target="w1", size="double"))

    await _plan("make the loss chart full width")

    options = _target_options(calls)
    assert options == {
        "w1": 'Chart "Tree cover loss per year" in section "Overview"',
        "w2": 'Map "Tree cover loss" at the top level',
        "w3": 'Chart "Tree cover loss due to fires" in section "Fires"',
        "w4": 'Imagery "Sentinel-2 imagery" at the top level',
        o.NONE: o.TARGET_NONE,
    }


async def test_remove_targets_hold_the_widgets_and_the_sections(jev, clairic):
    calls = jev(_first("remove"), _round(target="s2", widgets="keep_widgets"))

    await _plan("remove the fires section")

    options = _target_options(calls)
    assert options["s1"] == 'Section "Overview" (1 widget)'
    assert options["s2"] == 'Section "Fires" (1 widget)'
    assert "w4" in options
    assert "widgets" in calls[-1][1]


async def test_rename_targets_are_the_dashboard_and_the_sections(jev, clairic):
    calls = jev(_first("rename"), _round(target="dashboard"))
    clairic(title="Pará fires")

    await _plan("rename the dashboard to Pará fires")

    assert set(_target_options(calls)) == {"dashboard", "s1", "s2", o.NONE}


async def test_last_edit_targets_come_first_and_are_marked(jev, clairic):
    calls = jev(_first("remove"), _round(target="w3"))
    current = PAGE.model_copy(update={"last_widget_ids": ["w-fire"]})

    plan = await _plan("remove that", current=current)

    keys = list(_target_options(calls))
    assert keys[0] == "w3"
    assert _target_options(calls)["w3"].startswith(edits.LAST_EDIT)
    assert "Last edit: Chart" in calls[-1][0]
    assert plan.steps[0].args["widget_id"] == "w-fire"


async def test_last_section_ids_mark_a_section(jev, clairic):
    calls = jev(_first("remove"), _round(target="s2", widgets="with_widgets"))
    current = PAGE.model_copy(update={"last_section_ids": ["sec-fires"]})

    await _plan("remove that", current=current)

    assert list(_target_options(calls))[0] == "s2"


async def test_a_target_that_is_not_found_changes_nothing(jev, clairic):
    jev(_first("remove"), _round(target=o.NONE))

    plan = await _plan("remove the land cover chart")

    assert plan.steps == []
    assert plan.notes == [edits.NOTE_NO_TARGET]
    assert plan.tier is None


async def test_the_target_decision_holds_the_next_targets(jev, clairic):
    jev(
        _first("remove"),
        _round(target=_answer("w1", 0.5, w3=0.4, w2=0.05, none=0.05)),
    )

    plan = await _plan("remove the loss chart")

    target = next(d for d in plan.decisions if d.key == "target")
    assert target.clear is False
    assert target.value == "widget:w-loss"
    assert [opt.value for opt in target.options] == [
        "widget:w-fire",
        "widget:w-map",
    ]
    assert target.options[0].label.startswith('Chart "Tree cover loss due')


async def test_choose_replaces_the_jev_target(jev, clairic):
    jev(
        _first("move"),
        _round(target=_answer("w1", 0.5, w3=0.4), destination="top"),
    )

    plan = await _plan(
        "move the loss chart to the top",
        choose={"target": "widget:w-fire"},
    )

    assert plan.steps[0].args["widget_id"] == "w-fire"
    target = next(d for d in plan.decisions if d.key == "target")
    assert target.source == "user"
    assert target.clear is True
    assert plan.tier == 1


async def test_choose_with_an_unknown_value_keeps_the_jev_answer(jev, clairic):
    jev(_first("move"), _round(target="w1", destination="top"))

    plan = await _plan(
        "move the loss chart to the top", choose={"target": "widget:nope"}
    )

    assert plan.steps[0].args["widget_id"] == "w-loss"


# --- move ---------------------------------------------------------------------


async def test_move_to_a_section(jev, clairic):
    jev(_first("move"), _round(target="w2", destination="s2"))

    plan = await _plan("move the loss map to the fires section")

    step = plan.steps[0]
    assert step.kind == "move"
    assert step.args == {
        "dashboard_id": BOARD.id,
        "widget_id": "w-map",
        "widget_label": 'Map "Tree cover loss" at the top level',
        "destination_label": 'section "Fires"',
        "patch": {"section_id": "sec-fires"},
    }
    assert plan.tier == 1
    assert plan.state.last_widget_ids == ["w-map"]


async def test_move_to_the_top_level_sends_a_null_section(jev, clairic):
    jev(_first("move"), _round(target="w1", destination="top"))

    plan = await _plan("take the loss chart out of its section")

    assert plan.steps[0].args["patch"] == {"section_id": None}
    assert plan.steps[0].detail == "to the top level"


async def test_move_to_the_same_place_changes_nothing(jev, clairic):
    jev(_first("move"), _round(target="w1", destination="s1"))

    plan = await _plan("move the loss chart to the overview")

    assert plan.steps == []
    assert "already in" in plan.notes[0]


async def test_move_to_a_place_that_is_not_there_changes_nothing(jev, clairic):
    jev(_first("move"), _round(target="w1", destination=o.NONE))

    plan = await _plan("move the loss chart to the drivers section")

    assert plan.steps == []
    assert plan.notes == [edits.NOTE_NO_DESTINATION]


async def test_an_unclear_destination_needs_a_confirmation(jev, clairic):
    jev(
        _first("move"),
        _round(target="w1", destination=_answer("s2", 0.55, top=0.4)),
    )

    plan = await _plan("move the loss chart down")

    assert plan.tier == 2
    assert plan.needs_confirmation is True


# --- resize -------------------------------------------------------------------


async def test_resize_sends_the_full_config(jev, clairic):
    jev(_first("resize"), _round(target="w1", size="double"))

    plan = await _plan("make the loss chart full width")

    args = plan.steps[0].args
    assert args["size"] == "double"
    # The endpoint replaces the config: the other keys stay.
    assert args["patch"] == {
        "config": {
            "default_view": "chart",
            "chartIds": ["c1"],
            "size": "double",
        }
    }
    assert plan.steps[0].detail == "full width (was half width)"
    assert plan.tier == 1


async def test_resize_to_the_same_width_changes_nothing(jev, clairic):
    # A map with no size is full width.
    jev(_first("resize"), _round(target="w2", size="double"))

    plan = await _plan("make the loss map full width")

    assert plan.steps == []
    assert "already full width" in plan.notes[0]


# --- rename -------------------------------------------------------------------


async def test_rename_a_section(jev, clairic):
    jev(_first("rename"), _round(target="s2"))
    clairic(title="Fire season")

    plan = await _plan("rename the fires section to Fire season")

    step = plan.steps[0]
    assert step.kind == "rename"
    assert step.args == {
        "dashboard_id": BOARD.id,
        "target_type": "section",
        "section_id": "sec-fires",
        "old_title": "Fires",
        "title": "Fire season",
        "patch": {"title": "Fire season"},
    }
    assert plan.tier == 1
    assert plan.state.last_section_ids == ["sec-fires"]


async def test_rename_the_dashboard(jev, clairic):
    jev(_first("rename"), _round(target="dashboard"))
    clairic(title="Pará fires")

    plan = await _plan("call this dashboard Pará fires")

    args = plan.steps[0].args
    assert args["target_type"] == "dashboard"
    assert args["section_id"] is None
    assert args["patch"] == {"name": "Pará fires"}


async def test_rename_with_no_title_asks_no_target(jev, clairic):
    calls = jev(_first("rename"))
    clairic(title=None)

    plan = await _plan("rename the fires section")

    assert plan.steps == []
    assert plan.notes == [edits.NOTE_NO_TITLE]
    assert len(calls) == 1


async def test_rename_when_clairic_fails_changes_nothing(jev, clairic):
    jev(_first("rename"))
    clairic(fail=True)

    plan = await _plan("rename the fires section to Fire season")

    assert plan.notes == [edits.NOTE_NO_TITLE]


# --- change_period ------------------------------------------------------------


async def test_change_period_of_a_chart_replaces_it(jev, clairic):
    jev(_first("change_period"), _round(target="w1"))
    clairic(time=("2015-01-01", "2020-12-31"))

    plan = await _plan("show the loss chart for 2015 to 2020")

    step = plan.steps[0]
    assert step.kind == "change_period"
    args = step.args
    assert args["widget_id"] == "w-loss"
    assert args["replace"] is True
    assert args["old_start_date"] == "2001-01-01"
    assert args["analyze"] == {
        "aois": [
            {
                "source": "gadm",
                "src_id": "BRA.14_1",
                "subtype": "state-province",
            }
        ],
        "dataset_id": 4,
        "start_date": "2015-01-01",
        "end_date": "2020-12-31",
        "context_layer": "primary_forest",
        "canopy_cover": 30,
    }
    # The place of the old widget; the old chart ids do not stay.
    assert args["widget"] == {
        "widget_type": "insight",
        "insight_id": None,
        "config": {"default_view": "chart", "size": "single"},
        "position": 0,
        "section_id": "sec-overview",
    }
    assert plan.tier == 2
    assert plan.needs_confirmation is True
    assert plan.state.dataset_id == 4
    assert plan.state.start_date == "2015-01-01"


async def test_change_period_of_a_map_gives_a_new_layer(jev, clairic):
    jev(_first("change_period"), _round(target="w2"))
    clairic(time=("2020-01-01", "2020-12-31"))

    plan = await _plan("show 2020 on the loss map")

    args = plan.steps[0].args
    assert args["analyze"] is None
    layer = args["widget"]["config"]["dataset"]
    assert layer["dataset_id"] == 4
    assert str(layer["start_date"]) == "2020-01-01"
    assert args["widget"]["section_id"] is None


async def test_change_period_can_keep_the_old_widget(
    jev, clairic, monkeypatch
):
    monkeypatch.setattr(edits, "CHANGE_PERIOD_REPLACES", False)
    jev(_first("change_period"), _round(target="w1"))
    clairic(time=("2015-01-01", "2020-12-31"))

    plan = await _plan("show the loss chart for 2015 to 2020")

    assert plan.steps[0].args["replace"] is False
    assert "next to it" in plan.steps[0].detail


async def test_change_period_with_no_time_asks_no_target(jev, clairic):
    calls = jev(_first("change_period"))

    plan = await _plan("change the period of the loss chart")

    assert plan.steps == []
    assert plan.notes == [edits.NOTE_NO_PERIOD]
    assert len(calls) == 1


async def test_change_period_targets_only_widgets_with_data(jev, clairic):
    calls = jev(_first("change_period"), _round(target="w1"))
    clairic(time=("2015-01-01", "2020-12-31"))

    await _plan("show the loss chart since 2015")

    # The imagery widget has no analysis.
    assert "w4" not in _target_options(calls)


async def test_change_period_to_the_same_dates_changes_nothing(jev, clairic):
    jev(_first("change_period"), _round(target="w2"))
    clairic(time=("2001-01-01", "2025-12-31"))

    plan = await _plan("show the loss map for 2001 to 2025")

    assert plan.steps == []
    assert "already shows" in plan.notes[0]


# --- remove -------------------------------------------------------------------


async def test_remove_a_widget_always_needs_a_confirmation(jev, clairic):
    jev(_first("remove"), _round(target="w2", widgets="keep_widgets"))

    plan = await _plan("remove the loss map")

    step = plan.steps[0]
    assert step.kind == "remove"
    assert step.args == {
        "dashboard_id": BOARD.id,
        "target_type": "widget",
        "widget_id": "w-map",
        "section_id": None,
        "label": 'Map "Tree cover loss" at the top level',
        "delete_widgets": False,
        "widget_labels": [],
    }
    # Clear decisions, still tier 2.
    assert all(d.clear for d in plan.decisions)
    assert plan.tier == 2
    assert plan.needs_confirmation is True
    # The widgets question is not a decision of a widget removal.
    assert "widgets" not in {d.key for d in plan.decisions}
    assert plan.state.last_widget_ids is None


async def test_remove_a_section_and_keep_its_widgets(jev, clairic):
    jev(_first("remove"), _round(target="s2", widgets="keep_widgets"))

    plan = await _plan("remove the fires section but keep the chart")

    args = plan.steps[0].args
    assert args["target_type"] == "section"
    assert args["section_id"] == "sec-fires"
    assert args["delete_widgets"] is False
    assert args["widget_labels"] == [
        'Chart "Tree cover loss due to fires" in section "Fires"'
    ]
    assert plan.steps[0].detail == "its 1 widget moves to the top level"
    assert plan.needs_confirmation is True


async def test_remove_a_section_with_its_widgets(jev, clairic):
    jev(_first("remove"), _round(target="s2", widgets="with_widgets"))

    plan = await _plan("remove the fires section and everything in it")

    assert plan.steps[0].args["delete_widgets"] is True
    assert plan.steps[0].detail == "and its 1 widget"
    assert plan.tier == 2


async def test_remove_on_an_empty_dashboard_asks_no_target(jev, clairic):
    calls = jev(_first("remove"))
    board = zd.ZapDashboard(id="d1", name="Empty", area=PARA)

    plan = await planner.plan_zap(
        "remove that", PAGE, "owner", TODAY, dashboard=board
    )

    assert plan.notes == [edits.NOTE_NOTHING["remove"]]
    assert len(calls) == 1


# --- Actions that stay outside zap -----------------------------------------------


async def test_delete_and_publish_stay_outside_zap(jev, clairic):
    calls = jev(_first("edit"))

    plan = await _plan("publish this dashboard")

    assert plan.steps == []
    assert plan.notes == [zd.NOTE_EDIT]
    assert len(calls) == 1


async def test_an_edit_is_not_blocked_by_the_scope(jev, clairic):
    first = _first("rename")
    first["scope"] = _answer("several")
    jev(first, _round(target="s2"))
    clairic(title="Pará and Amazonas")

    plan = await _plan("rename the fires section to Pará and Amazonas")

    assert [s.kind for s in plan.steps] == ["rename"]


# --- Tiers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("clear", "action", "changed", "tier"),
    [
        ([True, True], "move", 1, 1),
        ([True, False], "move", 1, 2),
        ([True, True], "resize", 1, 1),
        ([True, True], "rename", 0, 1),
        ([True, True], "add_section", 0, 1),
        ([True, True], "remove", 1, 2),
        ([True, True], "change_period", 1, 2),
        ([True, True], "remove", 0, 2),
        # More than one widget.
        ([True, True], "move", 2, 2),
        ([True, None], "add_chart", 0, 1),
    ],
)
def test_dashboard_tier(clear, action, changed, tier):
    assert dashboard_tier(clear, action, changed) == tier


def test_board_from_texts_gets_items():
    board = zd.ZapDashboard(
        id="d1",
        name="x",
        area=PARA,
        sections=["Overview"],
        widgets=["chart: Loss", "map: Sentinel-2 imagery", "alerts list"],
    )
    assert [s.title for s in board.section_items] == ["Overview"]
    assert [(w.kind, w.title) for w in board.widget_items] == [
        ("Chart", "Loss"),
        ("Imagery", "Sentinel-2 imagery"),
        ("Alerts list", "alerts list"),
    ]


def test_board_from_items_gets_texts():
    assert BOARD.sections == ["Overview", "Fires"]
    assert BOARD.widgets == [
        "chart: Tree cover loss per year",
        "map: Tree cover loss",
        "chart: Tree cover loss due to fires",
        "map: Sentinel-2 imagery",
    ]


async def test_load_dashboard_gives_the_items(monkeypatch):
    from types import SimpleNamespace

    from src.api.services.zap import board as zb

    aoi = SimpleNamespace(
        source="gadm",
        src_id="BRA.14_1",
        subtype="state-province",
        name="Pará, Brazil",
        position=0,
    )
    row = SimpleNamespace(
        id="d1",
        user_id="owner",
        name="Pará forest",
        aois=[aoi],
        sections=[SimpleNamespace(id="s1", title="Fires", position=0)],
        widgets=[
            SimpleNamespace(
                id="w2",
                section_id="s1",
                widget_type="insight",
                position=0,
                insight_id="i1",
                config={},
            ),
            SimpleNamespace(
                id="w1",
                section_id=None,
                widget_type="map",
                position=0,
                insight_id=None,
                config={
                    "size": "single",
                    "dataset": {
                        "dataset_id": 4,
                        "dataset_name": "Tree cover loss",
                        "start_date": "2015-01-01",
                        "end_date": "2025-12-31",
                        "parameters": [
                            {"name": "canopy_cover", "values": [50]}
                        ],
                    },
                },
            ),
        ],
    )

    async def fake_get(dashboard_id):
        return row

    async def fake_titles(ids):
        return {"i1": "Loss due to fires"}

    async def fake_analyses(ids):
        return {"i1": {"dataset_id": 10, "start_date": "2001-01-01"}}

    monkeypatch.setattr(zb.dashboard_writer, "get_dashboard", fake_get)
    monkeypatch.setattr(zb, "_chart_titles", fake_titles)
    monkeypatch.setattr(zb, "_insight_analyses", fake_analyses)

    board = await zb.load_dashboard("d1", "owner")

    # The top level first.
    assert [w.id for w in board.widget_items] == ["w1", "w2"]
    loss_map, chart = board.widget_items
    assert loss_map.size == "single"
    assert loss_map.analysis == {
        "dataset_id": 4,
        "start_date": "2015-01-01",
        "end_date": "2025-12-31",
        "context_layer": None,
        "canopy_cover": 50,
    }
    assert chart.title == "Loss due to fires"
    assert chart.size == "double"
    assert chart.analysis["dataset_id"] == 10
    assert zb.widget_label(board, chart) == (
        'Chart "Loss due to fires" in section "Fires"'
    )
    assert board.widgets == [
        "map: Tree cover loss",
        "chart: Loss due to fires",
    ]
