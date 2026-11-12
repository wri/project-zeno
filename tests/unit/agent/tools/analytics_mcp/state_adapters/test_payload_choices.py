import pytest

from src.agent.tools.analytics_mcp.state_adapters.payload_choices import (
    PayloadChoices,
)

choices = PayloadChoices(
    default_canopy_cover=30, natural_forest_canopy_cover=10
)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"forest_filter": "natural_forest_only"}, "natural_forest"),
        ({"forest_filter": "primary_forest"}, "primary_forest"),
        ({"land_filter": "natural_lands"}, "natural_lands"),
        ({"forest_filter": None}, None),
    ],
)
def test_context_layer_is_the_filter_the_payload_applied(payload, expected):
    assert choices.context_layer(payload) == expected


@pytest.mark.parametrize(
    ("payload", "context_layer"),
    [
        ({"canopy_cover": 30}, None),
        ({"canopy_cover": 10}, "natural_forest"),
        ({}, None),
    ],
)
def test_default_canopy_cover_is_not_a_choice(payload, context_layer):
    assert choices.canopy_cover(payload, context_layer) is None


def test_other_canopy_cover_is_a_choice():
    assert choices.canopy_cover({"canopy_cover": 50}, None) == 50
