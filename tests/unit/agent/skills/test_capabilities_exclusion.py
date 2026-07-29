"""The capabilities listing hides datasets the current profile excludes, so
the agent never advertises a dataset it can't select."""

from src.agent.skills.capabilities import load_datasets_info
from src.agent.tool_spec import Availability, set_bound_availability


def test_capabilities_omits_excluded_dataset():
    set_bound_availability(
        Availability(
            skills=frozenset(),
            tools=frozenset(),
            excluded_datasets=frozenset({"Land GHG Inventory"}),
        )
    )
    try:
        listing = load_datasets_info()
    finally:
        set_bound_availability(Availability(frozenset(), frozenset()))
    assert "Land GHG Inventory" not in listing


def test_capabilities_lists_dataset_when_not_excluded():
    set_bound_availability(Availability(frozenset(), frozenset()))
    assert "Land GHG Inventory" in load_datasets_info()
