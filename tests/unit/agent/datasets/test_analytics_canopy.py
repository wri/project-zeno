"""The canopy cover threshold an analytics pull sends, and the catalog merge
the pull applies first. Saved insights record the same value, so the handler
and the insight builders share these functions."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    DEFAULT_CANOPY_COVER,
    INTEGRATED_ALERTS_ID,
    LAND_GHG_INVENTORY_ID,
    NATURAL_FOREST_DEFAULT_CANOPY_COVER,
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
    canopy_cover_threshold,
    with_catalog_record,
)


def _canopy(values):
    return [{"name": "canopy_cover", "values": values}]


def _threshold(dataset: dict):
    """The threshold the payload builder reads from a pulled dataset."""
    return canopy_cover_threshold(
        dataset.get("dataset_id"),
        dataset.get("context_layer"),
        dataset.get("parameters"),
    )


def test_tree_cover_loss_without_a_threshold_takes_the_default():
    dataset = {"dataset_id": TREE_COVER_LOSS_ID, "parameters": None}
    assert _threshold(dataset) == DEFAULT_CANOPY_COVER


def test_natural_forest_takes_its_own_default():
    dataset = {
        "dataset_id": TREE_COVER_LOSS_ID,
        "context_layer": "natural_forest",
        "parameters": None,
    }
    assert _threshold(dataset) == NATURAL_FOREST_DEFAULT_CANOPY_COVER


def test_a_selected_threshold_wins_and_takes_the_highest_value():
    dataset = {
        "dataset_id": TREE_COVER_LOSS_ID,
        "context_layer": "natural_forest",
        "parameters": [
            {"name": "other", "values": [99]},
            *_canopy([25, 50]),
        ],
    }
    assert _threshold(dataset) == 50


@pytest.mark.parametrize(
    "dataset_id", [INTEGRATED_ALERTS_ID, LAND_GHG_INVENTORY_ID, None]
)
def test_datasets_without_a_threshold_give_none(dataset_id):
    dataset = {"dataset_id": dataset_id, "parameters": _canopy([50])}
    assert _threshold(dataset) is None


def test_the_selection_wins_over_the_catalog_record():
    merged = with_catalog_record(
        {"dataset_id": TREE_COVER_LOSS_ID, "parameters": None}
    )
    assert merged["parameters"] is None
    assert merged["dataset_name"] == "Tree cover loss"


def test_a_selection_without_parameters_gets_the_catalog_list():
    record = next(
        ds for ds in DATASETS if ds["dataset_id"] == TREE_COVER_LOSS_ID
    )
    merged = with_catalog_record({"dataset_id": TREE_COVER_LOSS_ID})
    assert merged["parameters"] == record["parameters"]


def test_an_unknown_dataset_raises():
    with pytest.raises(ValueError, match="Dataset not found"):
        with_catalog_record({"dataset_id": 9999})


async def test_the_payload_sends_the_effective_threshold():
    dataset = with_catalog_record(
        {
            "dataset_id": TREE_COVER_LOSS_ID,
            "context_layer": "natural_forest",
            "parameters": None,
        }
    )
    payload = await AnalyticsHandler()._build_payload(
        dataset,
        [{"source": "gadm", "src_id": "BRA", "subtype": "country"}],
        "2021-01-01",
        "2024-12-31",
    )
    assert payload["canopy_cover"] == _threshold(dataset)


async def test_a_dataset_without_a_threshold_sends_none():
    dataset = with_catalog_record({"dataset_id": INTEGRATED_ALERTS_ID})
    payload = await AnalyticsHandler()._build_payload(
        dataset,
        [{"source": "gadm", "src_id": "BRA", "subtype": "country"}],
        "2024-01-01",
        "2024-12-31",
    )
    assert "canopy_cover" not in payload


class _Response:
    status_code = 200
    text = "{}"
    headers: dict = {}

    def json(self):
        return {"status": "success", "data": {}}


async def _pull(dataset: dict):
    handler = AnalyticsHandler()
    with (
        patch.object(
            handler, "_request_analysis", AsyncMock(return_value=_Response())
        ),
        patch.object(
            handler,
            "_process_response_data",
            AsyncMock(return_value=({"x": [1]}, 1, "ok", "https://a/b")),
        ),
    ):
        return await handler.pull_data(
            query="",
            dataset=dataset,
            start_date="2021-01-01",
            end_date="2024-12-31",
            change_over_time_query=False,
            aois=[{"source": "gadm", "src_id": "BRA", "subtype": "country"}],
        )


async def test_a_pull_reports_the_canopy_cover_it_sent():
    result = await _pull(
        {
            "dataset_id": TREE_COVER_LOSS_ID,
            "context_layer": "natural_forest",
            "parameters": None,
        }
    )
    assert result.canopy_cover == NATURAL_FOREST_DEFAULT_CANOPY_COVER


async def test_a_pull_of_a_dataset_without_a_threshold_reports_none():
    result = await _pull({"dataset_id": INTEGRATED_ALERTS_ID})
    assert result.success
    assert result.canopy_cover is None
