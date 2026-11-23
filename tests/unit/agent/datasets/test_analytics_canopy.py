"""The canopy cover threshold an analytics pull sends, and reports on its
result."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    DEFAULT_CANOPY_COVER,
    INTEGRATED_ALERTS_ID,
    LAND_GHG_INVENTORY_ID,
    NATURAL_FOREST_DEFAULT_CANOPY_COVER,
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
    canopy_cover_threshold,
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


async def test_the_payload_sends_the_effective_threshold():
    dataset = {
        "dataset_id": TREE_COVER_LOSS_ID,
        "context_layer": "natural_forest",
        "parameters": None,
    }
    payload = await AnalyticsHandler()._build_payload(
        dataset,
        [{"source": "gadm", "src_id": "BRA", "subtype": "country"}],
        "2021-01-01",
        "2024-12-31",
    )
    assert payload["canopy_cover"] == _threshold(dataset)


async def test_a_dataset_without_a_threshold_sends_none():
    dataset = {"dataset_id": INTEGRATED_ALERTS_ID}
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
