"""json_reply_instruction: the prompt line that asks for a JSON reply.

Replaces schema-constrained decoding (PZB-1243): the keys and their types
are spelled out in the prompt, and the reply is parsed and validated by us.
Built up one test at a time, ordered by the transformation priority premise.
"""

from typing import Optional

import pytest
from pydantic import BaseModel

from src.agent.llms import json_reply_instruction
from src.agent.subagents.analyst.text_generator import InsightText


class _Pick(BaseModel):
    choice: str


def test_one_string_field():
    assert json_reply_instruction(_Pick) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'this key: "choice" (a string). Do not wrap it in code fences.'
    )


class _Place(BaseModel):
    name: str


def test_the_key_is_the_schemas_field_name():
    assert json_reply_instruction(_Place) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'this key: "name" (a string). Do not wrap it in code fences.'
    )


class _Count(BaseModel):
    total: int


def test_an_integer_field():
    assert json_reply_instruction(_Count) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'this key: "total" (an integer). Do not wrap it in code fences.'
    )


class _Share(BaseModel):
    percent: float


class _Flag(BaseModel):
    is_curated: bool


def test_a_float_field_is_a_number():
    assert json_reply_instruction(_Share) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'this key: "percent" (a number). Do not wrap it in code fences.'
    )


def test_a_boolean_field():
    assert json_reply_instruction(_Flag) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'this key: "is_curated" (a boolean). Do not wrap it in code fences.'
    )


class _Names(BaseModel):
    names: list[str]


def test_a_list_of_strings_is_an_array_of_strings():
    assert json_reply_instruction(_Names) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'this key: "names" (an array of strings). '
        "Do not wrap it in code fences."
    )


@pytest.mark.parametrize(
    ("item_type", "kind"),
    [
        (int, "an array of integers"),
        (float, "an array of numbers"),
        (bool, "an array of booleans"),
    ],
)
def test_lists_of_other_scalars(item_type, kind):
    class _Values(BaseModel):
        values: list[item_type]

    assert json_reply_instruction(_Values) == (
        "Reply with a single JSON object and nothing else, with exactly "
        f'this key: "values" ({kind}). Do not wrap it in code fences.'
    )


def test_insight_text_instruction_is_exact():
    assert json_reply_instruction(InsightText) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'these keys: "primary_insight" (a string) and '
        '"follow_up_suggestions" (an array of strings). '
        "Do not wrap it in code fences."
    )


class _Row(BaseModel):
    state: str
    loss: float
    year: int
    is_curated: bool
    sources: list[str]


def test_many_fields_are_comma_separated_with_a_final_and():
    assert json_reply_instruction(_Row) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'these keys: "state" (a string), "loss" (a number), '
        '"year" (an integer), "is_curated" (a boolean) and '
        '"sources" (an array of strings). Do not wrap it in code fences.'
    )


class _WithNested(BaseModel):
    place: _Place


class _WithListOfNested(BaseModel):
    places: list[_Place]


class _WithOptional(BaseModel):
    note: Optional[str] = None


class _WithBareList(BaseModel):
    tags: list


class _WithDict(BaseModel):
    totals: dict[str, int]


@pytest.mark.parametrize(
    ("schema", "field", "type_name"),
    [
        (_WithNested, "place", "_Place"),
        (_WithListOfNested, "places", "list[_Place]"),
        (_WithOptional, "note", "str | None"),
        (_WithBareList, "tags", "list"),
        (_WithDict, "totals", "dict[str, int]"),
    ],
)
def test_unsupported_fields_raise_type_error(schema, field, type_name):
    with pytest.raises(TypeError) as raised:
        json_reply_instruction(schema)

    message = str(raised.value)
    assert f'Field "{field}" has type {type_name},' in message
    assert "tests." not in message  # no module path in the type name


def test_an_unsupported_field_is_reported_even_after_supported_ones():
    class _Mixed(BaseModel):
        state: str
        place: _Place

    with pytest.raises(TypeError, match='Field "place"'):
        json_reply_instruction(_Mixed)
