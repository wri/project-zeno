"""The analysis_inputs builders: one entry per pull, every key present, built
from a state dict or from a statistics row alike."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import structlog
from pydantic import ValidationError

from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    TREE_COVER_LOSS_ID,
)
from src.api.schemas import AnalysisInput
from src.api.services.analysis_inputs import (
    input_from_statistics,
    inputs_by_insight,
    inputs_from_statistics,
    statistics_dict,
)

ENTRY_KEYS = {
    "areas",
    "dataset_id",
    "dataset_name",
    "pulled_start_date",
    "pulled_end_date",
    "canopy_cover",
    "context_layer",
}


def _stat(**overrides):
    stat = {
        "id": "stat-1",
        "dataset_id": TREE_COVER_LOSS_ID,
        "dataset_name": "Tree cover loss",
        "start_date": "2001-01-01",
        "end_date": "2024-12-31",
        "aoi_names": ["Rondônia, Brazil"],
        "aoi_ids": ["BRA.22"],
        "aoi_sources": ["gadm"],
        "parameters": None,
        "context_layer": None,
        "canopy_cover": 30,
    }
    return {**stat, **overrides}


def test_an_entry_carries_the_pull_as_stored():
    assert input_from_statistics(_stat()) == {
        "areas": [
            {"name": "Rondônia, Brazil", "source": "gadm", "src_id": "BRA.22"}
        ],
        "dataset_id": TREE_COVER_LOSS_ID,
        "dataset_name": "Tree cover loss",
        "pulled_start_date": "2001-01-01",
        "pulled_end_date": "2024-12-31",
        "canopy_cover": 30,
        "context_layer": None,
    }


def test_the_canopy_cover_is_the_stored_one_never_worked_out_again():
    # The selection says 50, the pull sent 10: the stored value wins.
    stat = _stat(
        canopy_cover=10,
        parameters=[{"name": "canopy_cover", "values": [50]}],
    )
    assert input_from_statistics(stat)["canopy_cover"] == 10


def test_a_null_canopy_cover_stays_null():
    # A dataset without a threshold, or a pull stored before the column.
    assert (
        input_from_statistics(_stat(canopy_cover=None))["canopy_cover"] is None
    )
    stat = _stat()
    del stat["canopy_cover"]
    assert input_from_statistics(stat)["canopy_cover"] is None


def test_an_older_pull_without_ids_gives_null_ids():
    stat = _stat()
    del stat["aoi_ids"], stat["aoi_sources"], stat["dataset_id"]
    entry = input_from_statistics(stat)
    assert entry["areas"] == [
        {"name": "Rondônia, Brazil", "source": None, "src_id": None}
    ]
    assert entry["dataset_id"] is None


def test_ids_without_their_sources_are_not_used():
    stat = _stat(aoi_names=["A", "B"], aoi_ids=["1", "2"], aoi_sources=[])
    areas = input_from_statistics(stat)["areas"]
    assert [area["src_id"] for area in areas] == [None, None]


def test_every_key_is_present_with_explicit_nulls():
    entry = input_from_statistics(
        _stat(aoi_ids=[], aoi_sources=[], dataset_id=None, canopy_cover=None)
    )
    assert set(entry) == ENTRY_KEYS
    assert set(entry["areas"][0]) == {"name", "source", "src_id"}


def test_the_dates_say_they_are_the_dates_of_the_pull():
    fields = AnalysisInput.model_fields
    for name in ("pulled_start_date", "pulled_end_date"):
        assert "data pull" in fields[name].description
        assert "chart" in fields[name].description


def test_no_pulls_give_none_not_an_empty_list():
    assert inputs_from_statistics([]) is None


def test_repeated_pulls_give_one_entry_and_keep_the_order():
    first = _stat(id="a")
    other = _stat(id="b", start_date="2010-01-01")
    again = _stat(id="c")
    entries = inputs_from_statistics([first, other, again])
    assert [entry["pulled_start_date"] for entry in entries] == [
        "2001-01-01",
        "2010-01-01",
    ]


def test_an_entry_needs_every_field():
    with pytest.raises(ValidationError):
        AnalysisInput(  # type: ignore[call-arg]
            areas=[{"name": "Brazil"}],
            dataset_id=4,
            dataset_name="Tree cover loss",
            pulled_start_date="2001-01-01",
            pulled_end_date="2024-12-31",
            canopy_cover=None,
            context_layer=None,
        )


# --- from database rows ---------------------------------------------------


def _row(stat_id, **overrides):
    values = {
        "id": stat_id,
        "dataset_id": INTEGRATED_ALERTS_ID,
        "dataset_name": "Integrated alerts",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "aoi_names": ["Brazil"],
        "aoi_ids": ["BRA"],
        "aoi_sources": ["gadm"],
        "context_layer": None,
        "canopy_cover": None,
    }
    return SimpleNamespace(**{**values, **overrides})


def test_a_row_and_a_state_dict_give_the_same_entry():
    row = _row(uuid4(), canopy_cover=30, dataset_id=TREE_COVER_LOSS_ID)
    state = {**statistics_dict(row), "parameters": None}
    assert input_from_statistics(statistics_dict(row)) == (
        input_from_statistics(state)
    )


def _insight(statistics_ids, *, exact=True):
    return SimpleNamespace(
        id=uuid4(), statistics_ids=statistics_ids, statistics_ids_exact=exact
    )


def _session(*rows):
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows)
    session.execute = AsyncMock(return_value=result)
    return session


async def test_inputs_follow_statistics_ids_order_and_drop_repeats():
    a, b = _row(uuid4()), _row(uuid4(), dataset_name="Tree cover loss")
    insight = _insight([str(b.id), str(a.id), str(b.id)])
    session = _session(a, b)

    inputs = await inputs_by_insight(session, [insight])

    assert [e["dataset_name"] for e in inputs[insight.id]] == [
        "Tree cover loss",
        "Integrated alerts",
    ]
    # One query for the whole page.
    session.execute.assert_awaited_once()


async def test_an_insight_without_exact_links_has_null_inputs():
    a = _row(uuid4())
    old = _insight([str(a.id)], exact=False)
    session = _session(a)

    assert (await inputs_by_insight(session, [old])) == {old.id: None}
    # Nothing to look up: no query at all.
    session.execute.assert_not_awaited()


async def test_exact_links_to_no_pull_give_null_not_an_empty_list():
    none = _insight([])
    gone = _insight([str(uuid4())])
    with structlog.testing.capture_logs() as logs:
        inputs = await inputs_by_insight(_session(), [none, gone])
    assert inputs == {none.id: None, gone.id: None}
    assert any(
        log["event"] == "analysis_inputs_statistics_missing" for log in logs
    )


async def test_partly_missing_linked_rows_give_null_not_a_partial_list():
    a = _row(uuid4())
    partial = _insight([str(a.id), str(uuid4())])
    with structlog.testing.capture_logs() as logs:
        inputs = await inputs_by_insight(_session(a), [partial])
    assert inputs == {partial.id: None}
    assert any(
        log["event"] == "analysis_inputs_statistics_missing" for log in logs
    )


async def test_a_page_mixes_exact_and_old_insights():
    a = _row(uuid4())
    exact, old = _insight([str(a.id)]), _insight([str(a.id)], exact=False)
    inputs = await inputs_by_insight(_session(a), [exact, old])
    assert inputs[exact.id][0]["dataset_name"] == "Integrated alerts"
    assert inputs[old.id] is None
