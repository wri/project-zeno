"""The analytics API takes GADM admin areas by id down to level 5, so a
saved municipality is analysed like a country. The API itself rejects what
it can't compute on the fly, with a reason the agent relays."""

from unittest.mock import patch

import pytest

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
)

MUNICIPALITY = {
    "name": "Curitiba",
    "subtype": "municipality",
    "source": "gadm",
    "src_id": "BRA.16.137.1_1",
}


async def _pull(dataset_id: int, aois: list[dict]):
    with patch(
        "src.agent.datasets.handlers.analytics_handler.httpx.AsyncClient",
        side_effect=AssertionError("reached the analytics API"),
    ):
        return await AnalyticsHandler().pull_data(
            query="",
            dataset={"dataset_id": dataset_id},
            start_date="2001-01-01",
            end_date="2020-12-31",
            change_over_time_query=False,
            aois=aois,
        )


@pytest.mark.parametrize(
    "subtype", ["municipality", "locality", "neighbourhood"]
)
def test_admin_levels_3_to_5_are_sent_as_admin_ids(subtype):
    tree_cover_loss = {"dataset_id": TREE_COVER_LOSS_ID}
    assert (
        AnalyticsHandler()._get_aoi_type(
            {"subtype": subtype}, tree_cover_loss
        )["type"]
        == "admin"
    )


async def test_saved_municipality_is_pulled_by_admin_id():
    catalog = next(
        d for d in DATASETS if d["dataset_id"] == TREE_COVER_LOSS_ID
    )

    payload = await AnalyticsHandler()._build_payload(
        catalog, [dict(MUNICIPALITY)], "2001-01-01", "2020-12-31"
    )

    assert payload["aoi"]["type"] == "admin"
    assert payload["aoi"]["ids"] == ["BRA.16.137.1"]


async def test_saved_municipality_is_not_refused():
    # The request gets past every check and reaches the (patched) client.
    result = await _pull(TREE_COVER_LOSS_ID, [MUNICIPALITY])

    assert "reached the analytics API" in result.message
