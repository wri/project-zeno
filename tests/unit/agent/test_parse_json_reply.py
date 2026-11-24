"""parse_json_reply: turning Gemini's JSON reply text into a schema object.

The text stage asks for JSON by mime type, with no response schema
(PZB-1243), so the reply is parsed and validated here rather than by the
library. A reply that doesn't fit raises JsonReplyFormatError, which says
where and how it failed but never contains the reply text.
"""

import pytest
from pydantic import BaseModel

from src.agent import llms
from src.agent.llms import JsonReplyFormatError, parse_json_reply
from src.agent.subagents.analyst.text_generator import InsightText
from tests.unit.agent.fake_gemini import MODEL_VERSION, ScriptedGemini


class _Pick(BaseModel):
    choice: str


def _format_error(schema, reply) -> JsonReplyFormatError:
    with pytest.raises(JsonReplyFormatError) as raised:
        parse_json_reply(schema, reply)
    return raised.value


def test_a_reply_in_a_json_code_fence_parses():
    reply = '```json\n{"choice": "Paraná"}\n```'

    assert parse_json_reply(_Pick, reply) == _Pick(choice="Paraná")


def test_a_reply_in_a_bare_code_fence_parses():
    reply = '```\n{"choice": "Paraná"}\n```'

    assert parse_json_reply(_Pick, reply) == _Pick(choice="Paraná")


def test_whitespace_around_the_fence_is_ignored():
    reply = '\n  ```json\n{"choice": "Paraná"}\n```  \n'

    assert parse_json_reply(_Pick, reply) == _Pick(choice="Paraná")


def test_a_reply_that_is_not_json_is_a_format_error():
    with pytest.raises(JsonReplyFormatError):
        parse_json_reply(_Pick, "The answer is Paraná.")


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param('{"choice": "Para', id="truncated"),
        pytest.param('{"pick": "Paraná"}', id="missing key"),
        pytest.param('{"choice": ["Paraná"]}', id="wrong type"),
    ],
)
def test_other_malformed_replies_are_format_errors(reply):
    with pytest.raises(JsonReplyFormatError):
        parse_json_reply(_Pick, reply)


def test_a_blank_primary_insight_is_a_format_error():
    reply = '{"primary_insight": "  ", "follow_up_suggestions": []}'

    with pytest.raises(JsonReplyFormatError):
        parse_json_reply(InsightText, reply)


def test_a_primary_insight_of_only_control_characters_is_a_format_error():
    reply = r'{"primary_insight": "\u0000", "follow_up_suggestions": []}'

    with pytest.raises(JsonReplyFormatError):
        parse_json_reply(InsightText, reply)


def test_unparseable_text_is_reported_at_the_root():
    error = _format_error(_Pick, "The answer is Paraná.")

    assert error.errors == [("(root)", "json_invalid")]


def test_a_missing_key_is_reported_at_its_name():
    error = _format_error(_Pick, '{"pick": "Paraná"}')

    assert error.errors == [("choice", "missing")]


def test_a_wrong_type_is_reported_at_its_name():
    error = _format_error(_Pick, '{"choice": ["Paraná"]}')

    assert error.errors == [("choice", "string_type")]


def test_a_bad_list_item_is_reported_at_its_index():
    reply = '{"primary_insight": "Fine.", "follow_up_suggestions": [7]}'

    error = _format_error(InsightText, reply)

    assert error.errors == [("follow_up_suggestions.0", "string_type")]


def test_a_blank_primary_insight_is_reported_as_a_value_error():
    reply = '{"primary_insight": "  ", "follow_up_suggestions": []}'

    error = _format_error(InsightText, reply)

    assert error.errors == [("primary_insight", "value_error")]


def test_the_error_records_the_schema_and_the_reply_length():
    reply = '{"pick": "Paraná"}'

    error = _format_error(_Pick, reply)

    assert error.schema_name == "_Pick"
    assert error.reply_length == len(reply)


def test_the_error_message_says_where_but_never_quotes_the_reply():
    reply = '{"choice": ["Secret Paraná text"]}'

    message = str(_format_error(_Pick, reply))

    assert "_Pick" in message
    assert "choice: string_type" in message
    assert "Secret" not in message


class _RecordingLogger:
    """Collect each warning as (event, fields). Every other call does nothing.

    The module logger is swapped rather than using capture_logs, because
    cache_logger_on_first_use binds the logger on its first call and capture
    then misses the record (see tests/api/test_aoi_lookup.py).
    """

    def __init__(self):
        self.warnings = []

    def warning(self, event, **fields):
        self.warnings.append((event, fields))

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def warnings(monkeypatch):
    recorder = _RecordingLogger()
    monkeypatch.setattr(llms, "logger", recorder)
    return recorder.warnings


async def _fail_with(reply: str):
    model = ScriptedGemini.create(reply)
    with pytest.raises(JsonReplyFormatError):
        await llms.resilient_json_output(_Pick, model).ainvoke("q")


@pytest.mark.asyncio
async def test_a_format_error_logs_schema_model_version_errors_and_length(
    warnings,
):
    reply = '{"pick": "Paraná"}'

    await _fail_with(reply)

    assert warnings == [
        (
            "json_reply_format_error",
            {
                "schema": "_Pick",
                "model_version": MODEL_VERSION,
                "errors": [("choice", "missing")],
                "reply_length": len(reply),
            },
        )
    ]


@pytest.mark.asyncio
async def test_the_format_error_log_never_contains_the_reply_text(warnings):
    await _fail_with('{"choice": ["Secret Paraná text"]}')

    ((_, fields),) = warnings
    assert "Secret" not in repr(fields)
