"""Unit tests for the show_boundary_layer tool."""

import typing

import pytest

from src.agent.tools.show_boundary_layer import (
    BOUNDARY_LAYER_NUDGE,
    BOUNDARY_LAYERS,
    BoundaryLayerType,
    show_boundary_layer,
)
from src.shared.geocoding_helpers import CONCESSION_SOURCES


async def _call(**args):
    return await show_boundary_layer.ainvoke(
        {
            "type": "tool_call",
            "id": "call_1",
            "name": "show_boundary_layer",
            "args": args,
        }
    )


def test_layer_types_match_the_concession_sources():
    # The frontend upper-cases the source key to its boundary layer id, and
    # a clicked feature resolves through the same key on the backend.
    assert set(typing.get_args(BoundaryLayerType)) == set(CONCESSION_SOURCES)
    assert set(BOUNDARY_LAYERS) == set(CONCESSION_SOURCES)


@pytest.mark.asyncio
async def test_shows_the_layer_and_tells_the_user_to_click():
    command = await _call(layer="oil_palm")

    assert command.update["boundary_layer"] == {
        "source": "oil_palm",
        "name": "Oil palm concessions",
    }
    assert "nudge" not in command.update
    assert "aoi_selection" not in command.update
    (message,) = command.update["messages"]
    assert message.tool_call_id == "call_1"
    assert "Oil palm concessions" in message.content
    assert "click a concession" in message.content


@pytest.mark.asyncio
async def test_no_type_offers_every_type():
    command = await _call()

    assert "boundary_layer" not in command.update
    nudge = command.update["nudge"]
    assert nudge["type"] == BOUNDARY_LAYER_NUDGE
    assert nudge["options"] == list(BOUNDARY_LAYERS.values())
    (message,) = command.update["messages"]
    for name in BOUNDARY_LAYERS.values():
        assert name in message.content


@pytest.mark.asyncio
async def test_rejects_an_unknown_type():
    with pytest.raises(Exception):
        await _call(layer="soy")
