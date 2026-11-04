"""The analysis_inputs builders: one entry per pull, every key present."""

import pytest
from pydantic import ValidationError

from src.agent.datasets.handlers.analytics_handler import (
    DEFAULT_CANOPY_COVER,
    INTEGRATED_ALERTS_ID,
    NATURAL_FOREST_DEFAULT_CANOPY_COVER,
    TREE_COVER_LOSS_ID,
)
from src.api.services.analysis_inputs import (
    analysis_input,
    input_from_statistics,
    inputs_from_statistics,
)

ENTRY_KEYS = {
    "areas",
    "dataset_id",
    "dataset_name",
    "start_date",
    "end_date",
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
    }
    return {**stat, **overrides}


def test_an_entry_carries_the_pull_as_stored():
    assert input_from_statistics(_stat()) == {
        "areas": [
            {"name": "Rondônia, Brazil", "source": "gadm", "src_id": "BRA.22"}
        ],
        "dataset_id": TREE_COVER_LOSS_ID,
        "dataset_name": "Tree cover loss",
        "start_date": "2001-01-01",
        "end_date": "2024-12-31",
        "canopy_cover": DEFAULT_CANOPY_COVER,
        "context_layer": None,
    }


def test_canopy_is_the_highest_selected_value():
    stat = _stat(
        parameters=[{"name": "canopy_cover", "values": [25, 50]}],
    )
    assert input_from_statistics(stat)["canopy_cover"] == 50


def test_canopy_without_a_selection_is_the_default_the_pull_sent():
    stat = _stat(context_layer="natural_forest")
    entry = input_from_statistics(stat)
    assert entry["canopy_cover"] == NATURAL_FOREST_DEFAULT_CANOPY_COVER
    assert entry["context_layer"] == "natural_forest"


def test_canopy_is_null_for_a_dataset_without_a_threshold():
    stat = _stat(
        dataset_id=INTEGRATED_ALERTS_ID, context_layer="natural_lands"
    )
    entry = input_from_statistics(stat)
    assert entry["canopy_cover"] is None
    assert entry["context_layer"] == "natural_lands"


def test_an_older_pull_without_ids_gives_null_ids():
    stat = _stat()
    del stat["aoi_ids"], stat["aoi_sources"], stat["dataset_id"]
    entry = input_from_statistics(stat)
    assert entry["areas"] == [
        {"name": "Rondônia, Brazil", "source": None, "src_id": None}
    ]
    assert entry["dataset_id"] is None
    assert entry["canopy_cover"] is None


def test_ids_without_their_sources_are_not_used():
    stat = _stat(aoi_names=["A", "B"], aoi_ids=["1", "2"], aoi_sources=[])
    areas = input_from_statistics(stat)["areas"]
    assert [area["src_id"] for area in areas] == [None, None]


def test_every_key_is_present_with_explicit_nulls():
    entry = input_from_statistics(
        _stat(aoi_ids=[], aoi_sources=[], dataset_id=None)
    )
    assert set(entry) == ENTRY_KEYS
    assert set(entry["areas"][0]) == {"name", "source", "src_id"}


def test_no_pulls_give_none_not_an_empty_list():
    assert inputs_from_statistics([]) is None


def test_repeated_pulls_give_one_entry_and_keep_the_order():
    first = _stat(id="a")
    other = _stat(id="b", start_date="2010-01-01")
    again = _stat(id="c")
    entries = inputs_from_statistics([first, other, again])
    assert [entry["start_date"] for entry in entries] == [
        "2001-01-01",
        "2010-01-01",
    ]


def test_an_entry_needs_every_field():
    with pytest.raises(ValidationError):
        analysis_input(
            areas=[{"name": "Brazil"}],
            dataset_id=4,
            dataset_name="Tree cover loss",
            start_date="2001-01-01",
            end_date="2024-12-31",
            canopy_cover=None,
            context_layer=None,
        )
