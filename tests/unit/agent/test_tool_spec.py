"""Unit tests for the request-scoped bound-tool-names ContextVar."""

import pytest

from src.agent.tool_spec import bound_tool_names, set_bound_tool_names


@pytest.fixture(autouse=True)
def _reset_bound_tool_names():
    yield
    set_bound_tool_names(frozenset())


def test_bound_tool_names_defaults_to_empty():
    assert bound_tool_names() == frozenset()


def test_set_bound_tool_names_round_trips():
    set_bound_tool_names(frozenset({"pick_aoi", "pull_data"}))
    assert bound_tool_names() == frozenset({"pick_aoi", "pull_data"})


def test_set_bound_tool_names_overwrites_previous_value():
    set_bound_tool_names(frozenset({"pick_aoi"}))
    set_bound_tool_names(frozenset({"pull_data"}))
    assert bound_tool_names() == frozenset({"pull_data"})
