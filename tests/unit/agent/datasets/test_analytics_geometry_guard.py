"""Custom areas and concessions go to the analytics API as geometries. The
datasets and context layers that do not support a geometry must fail early,
with a reason, and without a request to the API."""

from unittest.mock import patch

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    LAND_GHG_INVENTORY_ID,
    TREE_COVER_GAIN_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
)

CUSTOM_AREA = {
    "name": "Heart of the Amazon",
    "subtype": "custom-area",
    "source": "custom",
    "src_id": "b89bcc67-fcbd-4cf8-8d08-38efdcba0cd2",
}
CONCESSION = {
    "name": "Green Gold Forestry",
    "subtype": "logging-concession",
    "source": "logging",
    "src_id": "30934",
}
BRAZIL = {
    "name": "Brazil",
    "subtype": "country",
    "source": "gadm",
    "src_id": "BRA",
}


async def _pull(dataset: dict, aois: list[dict]):
    with patch(
        "src.agent.datasets.handlers.analytics_handler.httpx.AsyncClient",
        side_effect=AssertionError("the analytics API must not be called"),
    ):
        return await AnalyticsHandler().pull_data(
            query="",
            dataset=dataset,
            start_date="2001-01-01",
            end_date="2020-12-31",
            change_over_time_query=False,
            aois=aois,
        )


@pytest.mark.parametrize(
    "dataset_id", [TREE_COVER_GAIN_ID, TREE_COVER_ID, LAND_GHG_INVENTORY_ID]
)
@pytest.mark.parametrize("aoi", [CUSTOM_AREA, CONCESSION])
async def test_unsupported_dataset_fails_early(dataset_id, aoi):
    result = await _pull({"dataset_id": dataset_id}, [aoi])

    assert not result.success
    assert "not available for custom areas or concessions" in result.message


@pytest.mark.parametrize(
    "dataset_id", [TREE_COVER_LOSS_ID, TREE_COVER_LOSS_BY_FIRES_ID]
)
async def test_intact_forest_fails_early(dataset_id):
    result = await _pull(
        {"dataset_id": dataset_id, "context_layer": "intact_forest"},
        [CUSTOM_AREA],
    )

    assert not result.success
    assert "intact_forest context layer" in result.message


async def test_mixed_selection_fails_early():
    result = await _pull(
        {"dataset_id": TREE_COVER_GAIN_ID}, [BRAZIL, CONCESSION]
    )

    assert not result.success


async def test_admin_area_is_not_blocked():
    # The guard lets the request through, so it reaches the (patched) client.
    result = await _pull({"dataset_id": TREE_COVER_GAIN_ID}, [BRAZIL])

    assert "must not be called" in result.message
