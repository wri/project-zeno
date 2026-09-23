"""ChatRequest input-source parsing (tracing contract, FE -> BE)."""

import typing

import pytest
from pydantic import ValidationError

from src.api.schemas import ChatRequest, InputSource


def _req(**kwargs) -> ChatRequest:
    return ChatRequest(query="Tree cover loss", **kwargs)


def test_input_source_defaults_to_typed():
    assert _req().input_source == "typed"


@pytest.mark.parametrize("source", typing.get_args(InputSource))
def test_every_known_input_source_is_accepted(source):
    kwargs = {"input_source": source}
    if source == "nudge":
        kwargs["nudge_response"] = {"type": "confirm", "option_index": 0}
    assert _req(**kwargs).input_source == source


def test_unknown_input_source_is_rejected():
    with pytest.raises(ValidationError):
        _req(input_source="voice")


def test_legacy_human_input_means_nudge():
    assert _req(query_type="human_input").input_source == "nudge"


def test_legacy_query_means_typed():
    assert _req(query_type="query").input_source == "typed"


def test_unknown_legacy_query_type_is_rejected():
    with pytest.raises(ValidationError):
        _req(query_type="other")


def test_explicit_input_source_beats_legacy_query_type():
    req = _req(input_source="starter_prompt", query_type="human_input")
    assert req.input_source == "starter_prompt"


def test_nudge_response_is_parsed():
    req = _req(
        input_source="nudge",
        nudge_response={"type": "dataset_choice", "option_index": 2},
    )
    assert req.nudge_response.type == "dataset_choice"
    assert req.nudge_response.option_index == 2


def test_nudge_response_allowed_with_legacy_human_input():
    req = _req(
        query_type="human_input",
        nudge_response={"type": "aoi_choice", "option_index": 0},
    )
    assert req.input_source == "nudge"


@pytest.mark.parametrize("source", ["typed", "starter_prompt"])
def test_nudge_response_with_non_nudge_source_is_rejected(source):
    with pytest.raises(ValidationError, match="nudge_response"):
        _req(
            input_source=source,
            nudge_response={"type": "confirm", "option_index": 0},
        )


def test_nudge_response_without_source_is_rejected():
    # Default source is typed, so a bare nudge_response is a contract error.
    with pytest.raises(ValidationError):
        _req(nudge_response={"type": "confirm", "option_index": 0})


@pytest.mark.parametrize(
    "response",
    [
        {"type": "confirm", "option_index": -1},
        {"type": "confirm"},
        {"option_index": 0},
        {"type": "x" * 65, "option_index": 0},
        {"type": "confirm", "option_index": 0, "extra": 1},
    ],
)
def test_malformed_nudge_response_is_rejected(response):
    with pytest.raises(ValidationError):
        _req(input_source="nudge", nudge_response=response)


def test_query_type_is_not_dumped():
    assert "query_type" not in _req(query_type="human_input").model_dump()


@pytest.mark.parametrize("nudge_type", ["", None])
def test_empty_nudge_type_is_accepted_as_none(nudge_type):
    req = _req(
        input_source="nudge",
        nudge_response={"type": nudge_type, "option_index": 1},
    )
    assert req.nudge_response.type is None
    assert req.nudge_response.option_index == 1
