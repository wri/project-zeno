"""Tests for the zap planner on a dashboard page, with jev and Clairic
mocked."""

from datetime import date
from types import SimpleNamespace

import pytest

from src.api.services.analysis_templates.registry import TEMPLATES
from src.api.services.mosaic import MosaicRecipe, encode_recipe
from src.api.services.zap import dashboard as zd
from src.api.services.zap import options as o
from src.api.services.zap import planner
from src.api.services.zap.extract import (
    ExtractError,
    NumberExtraction,
    TimeExtraction,
)
from src.api.services.zap.jev import Answer
from src.api.services.zap.models import ZapArea, ZapCurrent
from src.api.services.zap.tiers import clairic_clear, jev_clear

TODAY = date(2026, 11, 12)
PARA = ZapArea(
    name="Pará, Brazil",
    source="gadm",
    src_id="BRA.14_1",
    subtype="state-province",
)
BOARD = zd.ZapDashboard(
    id="5b0c4f9e-0000-4000-8000-000000000001",
    name="Pará forest",
    area=PARA,
    sections=["Overview"],
    widgets=["chart: Tree cover loss per year"],
)
PAGE = ZapCurrent(page="dashboard", dashboard_id=BOARD.id)


def _answer(choice, p=0.9, **others):
    """An answer with `p` for the choice and the rest spread on `others`."""
    probabilities = {choice: p, **others}
    return Answer(choice=choice, probability=p, probabilities=probabilities)


def _round(**choices):
    return {
        name: value if isinstance(value, Answer) else _answer(value)
        for name, value in choices.items()
    }


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
    def install(
        canopy=None,
        cloud=None,
        time=None,
        time_p=0.98,
        source="clairic",
        numbers_fail=False,
    ):
        numbers = (
            ExtractError("no answer")
            if numbers_fail
            else NumberExtraction(
                canopy=canopy,
                canopy_probability=0.97,
                cloud=cloud,
                cloud_probability=0.95,
            )
        )
        time_x = TimeExtraction(
            when="words" if time else None,
            range=time,
            source=source,
            probability=time_p,
        )

        async def fake_extract(prompt, today):
            return numbers, time_x

        monkeypatch.setattr(zd, "extract_dashboard", fake_extract)

    install()
    return install


def _first(action="add_chart", dataset="4", template=o.NONE, scope="single"):
    return _round(
        action=action,
        dataset=dataset,
        template=template,
        scope=scope,
        period=o.KEEP,
    )


async def _plan(prompt, current=PAGE, dashboard=BOARD):
    return await planner.plan_zap(
        prompt, current, "owner", TODAY, dashboard=dashboard
    )


async def test_add_chart_gives_the_analyze_body(jev, clairic):
    calls = jev(_first(), _round(context="primary_forest"))
    clairic(canopy=50, time=("2015-01-01", "2020-12-31"))

    plan = await _plan("add a chart of primary forest loss 2015-2020 at 50%")

    assert [s.kind for s in plan.steps] == ["add_chart"]
    args = plan.steps[0].args
    assert args["dashboard_id"] == BOARD.id
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
        "canopy_cover": 50,
    }
    assert args["widget"] == {
        "widget_type": "insight",
        "insight_id": None,
        "config": {"default_view": "chart"},
    }
    assert plan.tier == 1
    assert plan.needs_confirmation is False
    assert plan.state.page == "dashboard"
    assert plan.state.dataset_id == 4
    # No place question on a dashboard; the jev state is the dashboard.
    state, first = calls[0]
    assert "place" not in first
    assert "Current dashboard" in state
    assert "Tree cover loss per year" in state
    # Clairic gave the canopy cover, so jev call 2 has only the context.
    assert set(calls[1][1]) == {"context"}


async def test_add_map_gives_the_widget_body(jev, clairic):
    jev(_first(action="add_map", dataset="10"), _round(context=o.NONE))

    plan = await _plan("add a map of fire loss")

    assert [s.kind for s in plan.steps] == ["add_map"]
    widget = plan.steps[0].args["widget"]
    assert widget["widget_type"] == "map"
    config = widget["config"]
    assert config["default_view"] == "map"
    assert config["dataset"]["dataset_id"] == 10
    assert config["dataset"]["tile_url"]
    # The snapshot is the allowlist of dataset_config: no catalog prose.
    assert "description" not in config["dataset"]


async def test_add_template_gives_the_template_name(jev, clairic):
    jev(_first(action="add_template", template="forest-loss-drivers"))

    plan = await _plan("add the forest loss drivers section")

    assert [s.kind for s in plan.steps] == ["add_template"]
    assert plan.steps[0].args == {
        "dashboard_id": BOARD.id,
        "template": "forest-loss-drivers",
        "args": {},
    }
    assert plan.tier == 1


async def test_add_template_with_no_fit_adds_nothing(jev, clairic):
    jev(_first(action="add_template", template=o.NONE))

    plan = await _plan("add a section about water quality")

    assert plan.steps == []
    assert plan.notes == [zd.NOTE_NO_TEMPLATE]


async def test_add_imagery_gives_the_mosaic_and_the_widget(jev, clairic):
    jev(_first(action="add_imagery"))
    clairic(cloud=10, time=("2025-03-01", "2025-03-31"))

    plan = await _plan("add imagery of March 2025 with less than 10% clouds")

    assert [s.kind for s in plan.steps] == ["add_imagery"]
    args = plan.steps[0].args
    assert args["mosaic"] == {
        "source": "gadm",
        "src_id": "BRA.14_1",
        "target_date": "2025-03-16",
        "window_days": 15,
        "max_cloud_cover": 10,
        "max_items": 50,
    }
    imagery = args["widget"]["config"]["imagery"]
    # The same token that POST /mosaic/create makes for this query.
    assert imagery["mosaic_id"] == encode_recipe(
        MosaicRecipe(
            aois=(("gadm", "BRA.14_1"),),
            target_date=date(2025, 3, 16),
            window_days=15,
            max_cloud_cover=10,
            max_items=50,
        )
    )
    assert imagery["mosaic_id"] in imagery["tile_url"]
    assert imagery["aoi_names"] == ["Pará, Brazil"]
    assert {d.question for d in plan.decisions} >= {"Cloud cover", "Time"}


async def test_add_imagery_with_no_time_is_the_last_30_days(jev, clairic):
    jev(_first(action="add_imagery"))

    plan = await _plan("add satellite imagery")

    mosaic = plan.steps[0].args["mosaic"]
    assert mosaic["target_date"] == str(TODAY)
    assert mosaic["window_days"] == zd.IMAGERY_DEFAULT_WINDOW
    assert mosaic["max_cloud_cover"] == zd.IMAGERY_DEFAULT_CLOUD


async def test_imagery_before_sentinel2_adds_nothing(jev, clairic):
    jev(_first(action="add_imagery"))
    clairic(time=("2010-01-01", "2010-12-31"))

    plan = await _plan("add imagery from 2010")

    assert plan.steps == []
    assert plan.notes == [zd.NOTE_OLD_IMAGERY]


@pytest.mark.parametrize(
    ("action", "note"), [("edit", zd.NOTE_EDIT), (o.NONE, zd.NOTE_NONE)]
)
async def test_an_action_of_a_later_phase_adds_nothing(
    jev, clairic, action, note
):
    calls = jev(_first(action=action))

    plan = await _plan("remove the tree cover loss chart")

    assert plan.steps == []
    assert plan.notes == [note]
    assert plan.tier is None
    # No second jev call.
    assert len(calls) == 1


async def test_several_areas_add_nothing(jev, clairic):
    jev(_first(scope="several"))

    plan = await _plan("compare loss in Pará and Amazonas")

    assert plan.steps == []
    assert plan.notes == [zd.NOTE_SCOPE]


async def test_no_dataset_named_adds_nothing(jev, clairic):
    jev(_first(dataset=o.KEEP))

    plan = await _plan("add a chart")

    assert plan.steps == []
    assert plan.notes == [zd.NOTE_NO_DATASET]


async def test_an_unclear_action_needs_a_confirmation(jev, clairic):
    jev(
        _round(
            action=_answer("add_chart", 0.5, add_map=0.4, none=0.1),
            dataset="4",
            template=o.NONE,
            scope="single",
            period=o.KEEP,
        ),
        _round(context=o.NONE),
    )

    plan = await _plan("show tree cover loss")

    assert plan.tier == 2
    assert plan.needs_confirmation is True
    action = plan.decisions[0]
    assert action.question == "Action"
    assert action.clear is False
    assert [opt.label for opt in action.options] == [o.ACTIONS["add_map"]]


async def test_an_unclear_time_needs_a_confirmation(jev, clairic):
    jev(_first(), _round(context=o.NONE))
    clairic(time=("2020-01-01", "2020-12-31"), time_p=0.6)

    plan = await _plan("add a loss chart for maybe 2020")

    assert plan.needs_confirmation is True


async def test_numbers_call_fails_jev_gives_the_canopy(jev, clairic):
    calls = jev(_first(), _round(context=o.NONE, canopy="75"))
    clairic(numbers_fail=True)

    plan = await _plan("add a loss chart at 75% canopy")

    assert "canopy" in calls[1][1]
    assert plan.steps[0].args["analyze"]["canopy_cover"] == 75


async def test_a_follow_up_keeps_the_last_dataset(jev, clairic):
    jev(_first(action="add_map", dataset=o.KEEP), _round(context=o.KEEP))
    current = PAGE.model_copy(
        update={
            "dataset_id": 4,
            "context_layer": "primary_forest",
            "start_date": "2015-01-01",
            "end_date": "2025-12-31",
        }
    )

    plan = await _plan("and a map of it", current)

    dataset = plan.steps[0].args["widget"]["config"]["dataset"]
    assert dataset["dataset_id"] == 4
    assert dataset["context_layer"] == "primary_forest"
    assert dataset["start_date"] == "2015-01-01"


async def test_a_dashboard_the_user_cannot_edit_adds_nothing(
    jev, clairic, monkeypatch
):
    calls = jev()

    async def not_found(dashboard_id, user_id):
        return None

    monkeypatch.setattr(zd, "load_dashboard", not_found)

    plan = await planner.plan_zap("add a loss chart", PAGE, "other", TODAY)

    assert plan.steps == []
    assert plan.notes == [zd.NOTE_NOT_EDITABLE]
    assert calls == []


async def test_load_dashboard_is_for_the_owner_only(monkeypatch):
    aoi = SimpleNamespace(
        source="gadm",
        src_id="BRA.14_1",
        subtype="state-province",
        name="Pará, Brazil",
        position=0,
    )
    widget = SimpleNamespace(
        widget_type="map",
        position=0,
        insight_id=None,
        config={"dataset": {"dataset_name": "Tree cover loss"}},
    )
    row = SimpleNamespace(
        id="d1",
        user_id="owner",
        name="Pará forest",
        aois=[aoi],
        sections=[SimpleNamespace(title="Overview", position=0)],
        widgets=[widget],
    )

    async def fake_get(dashboard_id):
        return row

    monkeypatch.setattr(zd.dashboard_writer, "get_dashboard", fake_get)

    assert await zd.load_dashboard("d1", "someone-else") is None
    board = await zd.load_dashboard("d1", "owner")
    assert board.area.src_id == "BRA.14_1"
    assert board.area.subtype == "state-province"
    assert board.sections == ["Overview"]
    assert board.widgets == ["map: Tree cover loss"]


async def test_a_dashboard_with_no_area_adds_nothing(jev, clairic):
    jev()
    board = zd.ZapDashboard(id="d1", name="Empty", area=None)

    plan = await _plan("add a loss chart", dashboard=board)

    assert plan.notes == [zd.NOTE_NO_AREA]


def test_template_cards_agree_with_the_registry():
    assert set(o.TEMPLATE_CARDS) == {t.name for t in TEMPLATES}


@pytest.mark.parametrize(
    ("probabilities", "clear"),
    [
        ({"a": 0.9, "b": 0.1}, True),
        ({"a": 0.7, "b": 0.4}, True),
        ({"a": 0.69, "b": 0.0}, False),
        ({"a": 0.59, "b": 0.0}, False),
        ({"a": 0.7, "b": 0.5}, False),
        ({}, False),
    ],
)
def test_jev_clear(probabilities, clear):
    assert jev_clear("a", probabilities) is clear


@pytest.mark.parametrize(
    ("probability", "clear"),
    [(0.95, True), (0.81, True), (0.5, False), (0.79, False), (0.1, True)],
)
def test_clairic_clear(probability, clear):
    assert clairic_clear(probability) is clear


def test_imagery_window_of_a_range():
    assert zd._imagery_window(("2025-03-01", "2025-03-31"), TODAY) == (
        date(2025, 3, 16),
        15,
    )
    # A single day gets the minimum window.
    assert zd._imagery_window(("2025-06-15", "2025-06-15"), TODAY) == (
        date(2025, 6, 15),
        zd.IMAGERY_MIN_WINDOW,
    )
    # A long range is capped at the window that the endpoint permits.
    assert zd._imagery_window(("2016-01-01", "2025-12-31"), TODAY)[1] == (
        zd.IMAGERY_MAX_WINDOW
    )


def test_imagery_window_of_a_range_to_today_is_the_latest():
    # "recent": the last 12 months gives the latest month, not May.
    assert zd._imagery_window(("2025-11-12", "2026-11-12"), TODAY) == (
        TODAY,
        zd.IMAGERY_DEFAULT_WINDOW,
    )
    # "the last 2 weeks"
    assert zd._imagery_window(("2026-10-29", "2026-11-12"), TODAY) == (
        TODAY,
        14,
    )
