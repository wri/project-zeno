"""The canopy cover threshold sent to the analytics API. A dataset picked in
the UI arrives without `parameters`, and the catalog record it is merged
over lists every allowed canopy value. That list is never a choice, so the
selection must get the default threshold, not the highest allowed value."""

from unittest.mock import patch

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    CANOPY_COVER_DATASET_IDS,
    DEFAULT_CANOPY_COVER,
    NATURAL_FOREST_DEFAULT_CANOPY_COVER,
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
)
from src.api.services.chat import _with_catalog_layers

BRAZIL = {
    "name": "Brazil",
    "subtype": "country",
    "source": "gadm",
    "src_id": "BRA",
}


class _Sent(Exception):
    """Stops the pull once the request body is captured."""


class _CapturingClient:
    def __init__(self, sent: dict):
        self._sent = sent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers, json):
        self._sent.update(json)
        raise _Sent


async def _pull_payload(dataset: dict) -> dict:
    sent: dict = {}
    client = patch(
        "src.agent.datasets.handlers.analytics_handler.httpx.AsyncClient",
        return_value=_CapturingClient(sent),
    )
    with client:
        await AnalyticsHandler().pull_data(
            query="",
            dataset=dataset,
            start_date="2021-01-01",
            end_date="2023-12-31",
            change_over_time_query=False,
            aois=[BRAZIL],
        )
    assert sent, "the pull did not reach the analytics API"
    return sent


@pytest.mark.parametrize("dataset_id", sorted(CANOPY_COVER_DATASET_IDS))
async def test_selection_without_parameters_sends_the_default(dataset_id):
    payload = await _pull_payload({"dataset_id": dataset_id})

    assert payload["canopy_cover"] == DEFAULT_CANOPY_COVER


@pytest.mark.parametrize("dataset_id", sorted(CANOPY_COVER_DATASET_IDS))
async def test_natural_forest_without_parameters_sends_its_default(
    dataset_id,
):
    payload = await _pull_payload(
        {"dataset_id": dataset_id, "context_layer": "natural_forest"}
    )

    assert payload["canopy_cover"] == NATURAL_FOREST_DEFAULT_CANOPY_COVER


async def test_selected_threshold_is_sent():
    payload = await _pull_payload(
        {
            "dataset_id": TREE_COVER_LOSS_ID,
            "parameters": [{"name": "canopy_cover", "values": [50]}],
        }
    )

    assert payload["canopy_cover"] == 50


async def test_dataset_picked_in_the_ui_sends_the_default():
    # The shape the FE sends in ui_context.dataset_selected.dataset: no
    # `parameters` key. The chat service puts it into state["dataset"], and
    # pull_data receives that.
    picked = {
        "dataset_id": TREE_COVER_LOSS_ID,
        "dataset_name": "Tree cover loss",
    }
    assert "parameters" not in picked

    payload = await _pull_payload(_with_catalog_layers(picked))

    assert payload["canopy_cover"] == DEFAULT_CANOPY_COVER
