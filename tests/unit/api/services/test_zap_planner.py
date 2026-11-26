"""Tests for the zap planner: jev answers to plan steps."""

from datetime import date

import pandas as pd
import pytest

from src.api.services.zap import options as o
from src.api.services.zap import planner
from src.api.services.zap.extract import (
    ExtractError,
    PlaceExtraction,
    TimeExtraction,
)
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

    # These tests cover the jev path: Clairic does not answer.
    async def no_clairic(prompt, today):
        error = ExtractError("no answer")
        return error, error

    monkeypatch.setattr(planner, "extract", no_clairic)
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


# --- Clairic for the values, jev for the decisions --------------------------


@pytest.fixture
def clairic(monkeypatch, jev):
    """Answer the Clairic calls. `place=None` or `time=None` makes that call
    fail, so the planner uses jev for its values."""

    def install(place="unset", canopy=None, time="unset", source="clairic"):
        place_x = (
            ExtractError("no answer")
            if place is None
            else PlaceExtraction(
                place=None if place == "unset" else place,
                place_probability=0.99,
                canopy=canopy,
                canopy_probability=0.97,
            )
        )
        time_x = (
            ExtractError("no answer")
            if time is None
            else TimeExtraction(
                when=None if time == "unset" else "words",
                range=None if time == "unset" else time,
                source=source,
                probability=0.98,
            )
        )

        async def fake_extract(prompt, today):
            return place_x, time_x

        monkeypatch.setattr(planner, "extract", fake_extract)

    return install


def _sources(plan):
    return {d.question: d.source for d in plan.decisions}


PARA = ZapArea(name="Pará", source="gadm", src_id="BRA.14_1")


async def test_clairic_values_replace_the_jev_spans(jev, clairic):
    calls = jev(
        # jev also answers place and period; the planner does not use them.
        dict(dataset="4", place="Huelva", scope="single", period="2020"),
        dict(area="gadm:ESP.1.5_1", context=o.NONE),
    )
    clairic(
        place="Huelva, Spain",
        time=("2015-01-01", "2020-12-31"),
        canopy=50,
    )
    searched = []

    async def fake_search(name, sources, user_id, limit):
        searched.append(name)
        return pd.DataFrame([HUELVA])

    planner.search_aois = fake_search  # restored by monkeypatch in jev

    plan = await planner.plan_zap(
        "Loss in Huelva, Spain from 2015 to 2020 at 50% canopy",
        ZapCurrent(),
        "u",
        TODAY,
    )

    assert searched == ["Huelva, Spain"]
    dataset = plan.steps[0].args
    assert (dataset["start_date"], dataset["end_date"]) == (
        "2015-01-01",
        "2020-12-31",
    )
    assert dataset["parameters"][0]["values"] == [50]
    # Clairic gave the canopy cover, so jev does not get the question.
    assert "canopy" not in calls[1]
    assert _sources(plan) == {
        "Dataset": "jev",
        "Scope": "jev",
        "Area words": "clairic",
        "Time": "clairic",
        "Area": "jev",
        "Forest type": "jev",
        "Canopy cover": "clairic",
    }
    assert plan.state.dataset_id == 4
    assert plan.state.area.src_id == "ESP.1.5_1"
    assert plan.state.canopy_cover == 50


async def test_a_calendar_rule_is_recorded_as_code(jev, clairic):
    jev(
        dict(dataset="11", place=o.KEEP, scope="single", period=o.KEEP),
        dict(context=o.NONE),
    )
    clairic(time=("2026-03-01", "2026-03-31"), source="code")

    plan = await planner.plan_zap(
        "alerts in March 2026", ZapCurrent(), "u", TODAY
    )

    assert _sources(plan)["Time"] == "code"
    assert plan.steps[0].args["start_date"] == "2026-03-01"


async def test_canopy_snaps_to_a_permitted_value(jev, clairic):
    jev(
        dict(dataset="4", place=o.KEEP, scope="single", period=o.KEEP),
        dict(context=o.NONE),
    )
    clairic(canopy=12)

    plan = await planner.plan_zap(
        "loss at 12% canopy", ZapCurrent(), "u", TODAY
    )

    assert plan.steps[0].args["parameters"][0]["values"] == [10]
    assert plan.notes == []


async def test_a_far_canopy_value_adds_a_note(jev, clairic):
    jev(
        dict(dataset="4", place=o.KEEP, scope="single", period=o.KEEP),
        dict(context=o.NONE),
    )
    clairic(canopy=90)

    plan = await planner.plan_zap(
        "loss at 90% canopy", ZapCurrent(), "u", TODAY
    )

    assert plan.steps[0].args["parameters"][0]["values"] == [75]
    assert any("90%" in note for note in plan.notes)


async def test_place_call_fails_jev_gives_place_and_canopy(jev, clairic):
    calls = jev(
        dict(dataset="4", place="Huelva", scope="single", period=o.KEEP),
        dict(area="gadm:ESP.1.5_1", context=o.NONE, canopy="75"),
    )
    clairic(place=None, time=("2020-01-01", "2020-12-31"))

    plan = await planner.plan_zap("Huelva 2020 75%", ZapCurrent(), "u", TODAY)

    assert "canopy" in calls[1]
    sources = _sources(plan)
    assert sources["Area words"] == "jev"
    assert sources["Canopy cover"] == "jev"
    assert sources["Time"] == "clairic"
    assert plan.state.canopy_cover == 75
    assert plan.state.start_date == "2020-01-01"


async def test_time_call_fails_jev_gives_the_period(jev, clairic):
    jev(
        dict(dataset="4", place=o.KEEP, scope="single", period="since-2015"),
        dict(context=o.NONE),
    )
    clairic(time=None)

    plan = await planner.plan_zap("loss since 2015", ZapCurrent(), "u", TODAY)

    assert _sources(plan)["Time"] == "jev"
    assert plan.steps[0].args["start_date"] == "2015-01-01"


async def test_map_view_words_keep_the_area(jev, clairic):
    calls = jev(
        dict(dataset="10", place=o.KEEP, scope="single", period=o.KEEP),
        dict(context=o.NONE),
    )
    clairic(place="this area")

    plan = await planner.plan_zap(
        "fires in this area", ZapCurrent(dataset_id=4, area=PARA), "u", TODAY
    )

    assert "area" not in calls[1]
    assert [s.kind for s in plan.steps] == ["dataset", "analysis"]
    assert plan.state.area == PARA


# --- The full current state -------------------------------------------------


FULL = ZapCurrent(
    dataset_id=4,
    area=PARA,
    start_date="2010-01-01",
    end_date="2020-12-31",
    context_layer="primary_forest",
    canopy_cover=50,
)


async def test_follow_up_keeps_forest_type_canopy_and_dates(jev, clairic):
    calls = jev(
        dict(dataset="10", place=o.KEEP, scope="single", period=o.KEEP),
        dict(context=o.KEEP),
    )
    clairic()

    plan = await planner.plan_zap("fires instead", FULL, "u", TODAY)

    # jev can keep the forest type of the map.
    assert o.KEEP in calls[1]["context"].options
    dataset = plan.steps[0].args
    assert dataset["dataset_id"] == 10
    assert dataset["context_layer"] == "primary_forest"
    assert dataset["parameters"][0]["values"] == [50]
    assert (dataset["start_date"], dataset["end_date"]) == (
        "2010-01-01",
        "2020-12-31",
    )
    assert plan.state == FULL.model_copy(update={"dataset_id": 10})


async def test_new_time_keeps_the_rest(jev, clairic):
    jev(
        dict(dataset=o.KEEP, place=o.KEEP, scope="single", period=o.KEEP),
        dict(context=o.KEEP),
    )
    clairic(time=("2015-01-01", "2026-10-01"))

    plan = await planner.plan_zap("since 2015", FULL, "u", TODAY)

    assert plan.state.start_date == "2015-01-01"
    assert plan.state.end_date == "2025-12-31"  # clamped to the dataset
    assert plan.state.context_layer == "primary_forest"
    assert plan.state.canopy_cover == 50


async def test_nothing_named_changes_nothing(jev, clairic):
    jev(
        dict(dataset=o.KEEP, place=o.KEEP, scope="single", period=o.KEEP),
        dict(context=o.KEEP),
    )
    clairic()

    plan = await planner.plan_zap("thanks!", FULL, "u", TODAY)

    assert plan.steps == []
    assert plan.state == FULL


async def test_all_dates_of_a_dataset_are_not_a_period(jev, clairic):
    """The full dates of the old dataset give the full dates of the new."""
    jev(
        dict(dataset="2", place=o.KEEP, scope="single", period=o.KEEP),
    )
    clairic()
    current = ZapCurrent(
        dataset_id=4,
        area=PARA,
        start_date="2001-01-01",
        end_date="2025-12-31",
    )

    plan = await planner.plan_zap("grassland instead", current, "u", TODAY)

    dataset = plan.steps[0].args
    assert (dataset["start_date"], dataset["end_date"]) == (
        "2000-01-01",
        "2022-12-31",
    )


async def test_none_removes_the_forest_type(jev, clairic):
    jev(
        dict(dataset=o.KEEP, place=o.KEEP, scope="single", period=o.KEEP),
        dict(context=o.NONE),
    )
    clairic()

    plan = await planner.plan_zap("all tree cover", FULL, "u", TODAY)

    assert plan.steps[0].args["context_layer"] is None
    assert plan.state.context_layer is None
    assert plan.state.canopy_cover == 50


async def test_state_shows_the_driver_layer(jev, clairic):
    """Tree cover loss by driver always has the "driver" layer, and a
    follow-up with that state changes nothing."""
    jev(dict(dataset="8", place=o.KEEP, scope="single", period=o.KEEP))
    clairic()
    plan = await planner.plan_zap("drivers", ZapCurrent(area=PARA), "u", TODAY)
    assert plan.state.context_layer == "driver"

    jev(dict(dataset=o.KEEP, place=o.KEEP, scope="single", period=o.KEEP))
    again = await planner.plan_zap("thanks", plan.state, "u", TODAY)
    assert again.steps == []


# --- Phase 4: the other options of a decision, and the tier -----------------


async def test_map_decisions_carry_their_other_options(monkeypatch, jev):
    async def fake_decide(state, questions):
        if "dataset" in questions:
            return {
                "dataset": Answer(
                    choice="4",
                    probability=0.7,
                    probabilities={
                        "4": 0.7,
                        "10": 0.15,
                        o.KEEP: 0.08,
                        "8": 0.05,
                        "6": 0.01,
                        "1": 0.01,
                    },
                ),
                "place": Answer(choice="Huelva", probability=0.9),
                "scope": Answer(choice="single", probability=0.9),
                "period": Answer(choice=o.KEEP, probability=0.9),
            }
        return {
            "area": Answer(
                choice="gadm:ESP.1.5_1",
                probability=0.9,
                probabilities={"gadm:ESP.1.5_1": 0.9, o.NONE: 0.1},
            ),
            "context": Answer(choice=o.NONE, probability=0.9),
            "canopy": Answer(choice=o.NONE, probability=0.9),
        }

    monkeypatch.setattr(planner, "decide", fake_decide)

    plan = await planner.plan_zap("loss in Huelva", ZapCurrent(), "u", TODAY)

    dataset = next(d for d in plan.decisions if d.question == "Dataset")
    # Best first, at most three, with no "keep" option.
    assert [opt.label for opt in dataset.options] == [
        planner.CATALOG[10]["dataset_name"],
        planner.CATALOG[8]["dataset_name"],
        planner.CATALOG[6]["dataset_name"],
    ]
    assert dataset.options[0].probability == 0.15
    assert dataset.clear is True
    area = next(d for d in plan.decisions if d.question == "Area")
    assert area.label == "Huelva, Andalucía, Spain (state-province, gadm)"
    assert area.options == []
    # A map plan is tier 0 and needs no confirmation.
    assert plan.tier == 0
    assert plan.needs_confirmation is False


async def test_a_map_plan_with_no_steps_has_no_tier(jev):
    jev(dict(dataset=o.KEEP, place=o.KEEP, scope="single", period=o.KEEP))

    plan = await planner.plan_zap("hello", ZapCurrent(), "u", TODAY)

    assert plan.tier is None
    assert plan.needs_confirmation is None
