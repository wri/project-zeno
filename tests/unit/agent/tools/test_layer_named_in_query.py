"""`layer_named_in_query`: the context layer that a query names in words,
applied when the selection model leaves it out."""

import pytest

from src.agent.subagents.pick_dataset.tool import layer_named_in_query

LAYERS = [
    {"value": "primary_forest", "description": "Primary forest"},
    {"value": "intact_forest", "description": "Intact forest landscapes"},
    {"value": "natural_forest", "description": "Natural forest"},
]


@pytest.mark.parametrize(
    "query, expected",
    [
        ("tree cover loss in intact forest landscapes", "intact_forest"),
        ("How much loss in Primary Forest in Brazil?", "primary_forest"),
        ("loss in intact_forest in Russia", "intact_forest"),
        ("tree cover loss in Russia", None),
        ("deforestation in intact forests", "intact_forest"),
        # Two layers named: the rule cannot choose, so it leaves it out.
        ("primary forest and natural forest loss", None),
    ],
)
def test_names_one_layer(query, expected):
    assert layer_named_in_query(query, LAYERS) == expected


def test_only_layers_left_after_the_extent_filter():
    # A layer that the extent filter removed is not in the list.
    remaining = [
        layer for layer in LAYERS if layer["value"] != "intact_forest"
    ]
    assert layer_named_in_query("intact forest loss", remaining) is None


@pytest.mark.parametrize("layers", [None, float("nan"), [], [{"name": "x"}]])
def test_no_usable_layers(layers):
    assert layer_named_in_query("intact forest loss", layers) is None
