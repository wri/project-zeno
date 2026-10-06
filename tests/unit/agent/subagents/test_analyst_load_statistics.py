from unittest.mock import AsyncMock, patch

import pytest

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_LOSS_ID
from src.agent.subagents.analyst.tool import _load_statistics_data

pytestmark = pytest.mark.asyncio


async def test_refetched_natural_forest_data_keeps_only_natural_rows():
    raw = {
        "aoi_id": ["BRA.14", "BRA.14"],
        "natural_forests_class": ["Natural Forest", "Unknown"],
        "area_ha": [10.0, 3.0],
    }
    statistics = {
        "dataset_id": TREE_COVER_LOSS_ID,
        "context_layer": "natural_forest",
        "source_url": "https://analytics.example.com/result",
    }

    with patch(
        "src.agent.subagents.analyst.tool.fetch_statistics_from_url",
        AsyncMock(return_value=raw),
    ):
        data = await _load_statistics_data(statistics)

    assert data == {"aoi_id": ["BRA.14"], "area_ha": [10.0]}
