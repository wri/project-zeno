"""Tests for the zap planner: jev answers to plan steps."""

from datetime import date

import pandas as pd
import pytest

from src.api.services.zap import options as o
from src.api.services.zap import planner
from src.api.services.zap.jev import Answer
from src.api.services.zap.models import ZapArea, ZapCurrent

TODAY = date(2026, 10, 1)
HUELVA = {
    "src_id": "ESP.1.5_1",
    "name": "Huelva, Andalucía, Spain",
    "subtype": "state-province",
    "source": "gadm",
    "bbox": [-7.5, 37.0, -6.0, 38.2],
}


def _answers(**choices):
    return {k: Answer(choice=v, probability=0.9) for k, v in choices.items()}


@pytest.fixture
def jev(monkeypatch):
    """Answer each call with the next dict of choices; record the questions."""
    calls = []

    def install(*rounds):
        queue = list(rounds)

        async def fake_decide(state, questions):
            calls.append(questions)
            return _answers(**queue.pop(0))

        monkeypatch.setattr(planner, "decide", fake_decide)
        return calls

    async def fake_search(name, sources, user_id, limit):
        return pd.DataFrame([HUELVA])

    monkeypatch.setattr(planner, "search_aois", fake_search)
    return install


async def test_new_dataset_and_area_plan_three_steps(jev):
    calls = jev(
        dict(
            dataset="4",
            place="Huelva Spain",
            scope="single",
            period="since-2015",
        ),
        dict(area="gadm:ESP.1.5_1", context="primary_forest", canopy=o.NONE),
    )

    plan = await planner.plan_zap(
        "Deforestation in Huelva since 2015", ZapCurrent(), "u", TODAY
    )

    assert [s.kind for s in plan.steps] == ["dataset", "area", "analysis"]
    dataset = plan.steps[0].args
    assert dataset["dataset_id"] == 4
    assert dataset["context_layer"] == "primary_forest"
    assert dataset["start_date"] == "2015-01-01"
    assert plan.steps[1].args["src_id"] == "ESP.1.5_1"
    analysis = plan.steps[2].args
    assert analysis["area"]["name"] == "Huelva, Andalucía, Spain"
    assert analysis["context_layer"] == "primary_forest"
    assert analysis["canopy_cover"] is None
    # The second call offers only the options of the chosen dataset.
    assert set(calls[1]) == {"area", "context", "canopy"}


async def test_keep_everything_plans_nothing(jev):
    jev(dict(dataset=o.KEEP, place=o.KEEP, scope="single", period=o.KEEP))

    plan = await planner.plan_zap("hello", ZapCurrent(), "u", TODAY)

    assert plan.steps == []


async def test_new_area_keeps_dataset_and_reruns_charts(jev):
    jev(
        dict(dataset=o.KEEP, place="Huelva", scope="single", period=o.KEEP),
        dict(area="gadm:ESP.1.5_1", context=o.NONE, canopy=o.NONE),
    )
    current = ZapCurrent(dataset_id=4)

    plan = await planner.plan_zap("what about Huelva?", current, "u", TODAY)

    assert [s.kind for s in plan.steps] == ["area", "analysis"]
    assert plan.steps[1].args["dataset_id"] == 4


async def test_several_areas_go_to_the_assistant(jev):
    calls = jev(
        dict(dataset="4", place="countries", scope="global", period=o.KEEP),
        dict(context=o.NONE, canopy=o.NONE),
    )

    plan = await planner.plan_zap(
        "which countries lost most forest", ZapCurrent(), "u", TODAY
    )

    assert [s.kind for s in plan.steps] == ["dataset"]
    assert plan.notes
    assert "area" not in calls[1]


async def test_new_context_on_current_area_charts_again(jev):
    jev(
        dict(dataset=o.KEEP, place=o.KEEP, scope="single", period=o.KEEP),
        dict(context="primary_forest", canopy=o.NONE),
    )
    current = ZapCurrent(
        dataset_id=4,
        area=ZapArea(name="Pará", source="gadm", src_id="BRA.14_1"),
    )

    plan = await planner.plan_zap("only primary forest", current, "u", TODAY)

    assert [s.kind for s in plan.steps] == ["dataset", "analysis"]
    assert plan.steps[1].args["area"]["src_id"] == "BRA.14_1"


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("2020", ("2020-01-01", "2020-12-31")),
        ("since-2015", ("2015-01-01", "2026-10-01")),
        ("last-5-years", ("2021-01-01", "2026-10-01")),
        ("all", (None, None)),
    ],
)
def test_period_range(period, expected):
    assert o.period_range(period, TODAY) == expected


def test_place_spans_are_word_groups():
    spans = o.place_spans("Fires in Pará, Brazil")
    assert "Pará" in spans
    assert "Pará, Brazil" not in spans
    assert "Pará Brazil" in spans
    assert all(len(s.split()) <= o.MAX_SPAN for s in spans)
