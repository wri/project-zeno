"""pull_data writes the dataset back to state when it analyses a different
date range from the one pick_dataset resolved, so the map tiles and the
legend dates follow the analysis (PZB-1563)."""

import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult
from src.agent.tools import pull_data as pull_data_module
from src.agent.tools.pull_data import pull_data

BRAZIL = {
    "name": "Brazil",
    "subtype": "country",
    "source": "gadm",
    "src_id": "BRA",
}

# The dataset pick_dataset put in state on an earlier turn.
PICKED_ALERTS = {
    "dataset_id": INTEGRATED_ALERTS_ID,
    "dataset_name": "Integrated alerts",
    "context_layer": None,
    "selected_layer": None,
    "parameters": None,
    "start_date": "2023-12-01",
    "end_date": "2026-10-31",
    "tile_url": "https://tiles.example.com/alerts.png?start_date=2023-12-01",
    "layers": [],
    "context_layers": [],
    "reason": "",
}


@pytest.fixture(autouse=True)
def successful_pull(monkeypatch):
    class Orchestrator:
        async def pull_data(self, **kwargs):
            return DataPullResult(
                success=True,
                data={"aoi_id": ["BRA"], "name": ["Brazil"]},
                message="Pulled data.",
                analytics_api_url="https://analytics.example.com/result/1",
            )

    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_pool_session():
        yield session

    monkeypatch.setattr(
        pull_data_module, "data_pull_orchestrator", Orchestrator()
    )
    monkeypatch.setattr(
        pull_data_module, "get_session_from_pool", fake_pool_session
    )


async def _pull(start_date, end_date):
    return await pull_data.coroutine(
        query="integrated alerts in Brazil",
        state={
            "dataset": PICKED_ALERTS,
            "aoi_selection": {"name": "Brazil", "aois": [BRAZIL]},
        },
        start_date=start_date,
        end_date=end_date,
        tool_call_id="call-1",
    )


async def test_new_date_range_moves_the_dataset_layer_to_it():
    command = await _pull("2025-03-01", "2025-03-31")

    dataset = command.update["dataset"]
    assert dataset["start_date"] == "2025-03-01"
    assert dataset["end_date"] == "2025-03-31"
    assert dataset["tile_url"].endswith(
        "&start_date=2025-03-01&end_date=2025-03-31"
    )
    assert command.update["statistics"][0]["start_date"] == "2025-03-01"


async def test_same_date_range_leaves_the_dataset_alone():
    command = await _pull(
        PICKED_ALERTS["start_date"], PICKED_ALERTS["end_date"]
    )

    assert "dataset" not in command.update


async def test_tile_error_does_not_fail_the_pull(monkeypatch):
    def broken(*args):
        raise KeyError("dataset_id")

    monkeypatch.setattr(
        sys.modules["src.agent.subagents.pick_dataset"],
        "with_date_range",
        broken,
    )

    command = await _pull("2025-03-01", "2025-03-31")

    assert "dataset" not in command.update
    assert command.update["statistics"][0]["start_date"] == "2025-03-01"
