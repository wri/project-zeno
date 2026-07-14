"""Unit tests for the request-scoped bound-availability ContextVar."""

import pytest

from src.agent.tool_spec import (
    Availability,
    bound_availability,
    set_bound_availability,
)

_EMPTY = Availability(skills=frozenset(), tools=frozenset())


@pytest.fixture(autouse=True)
def _reset_bound_availability():
    yield
    set_bound_availability(_EMPTY)


def test_bound_availability_defaults_to_empty():
    assert bound_availability() == _EMPTY


def test_set_bound_availability_round_trips():
    available = Availability(
        skills=frozenset({"analyze"}),
        tools=frozenset({"pick_aoi", "pull_data"}),
    )
    set_bound_availability(available)
    assert bound_availability() == available


def test_set_bound_availability_overwrites_previous_value():
    set_bound_availability(
        Availability(skills=frozenset({"analyze"}), tools=frozenset())
    )
    set_bound_availability(
        Availability(skills=frozenset({"pull-data"}), tools=frozenset())
    )
    assert bound_availability().skills == frozenset({"pull-data"})
