"""resilient_json_output: a structured reply without schema-constrained
decoding.

PZB-1243: schema-constrained decoding (response_json_schema) is what makes
Gemini Flash emit control characters in place of accented letters. Gemini is
asked for JSON by mime type only, and the reply is parsed by us.
"""

import pytest
from pydantic import BaseModel

from src.agent import llms
from tests.unit.agent.fake_gemini import (
    RequestSpyGemini,
    ScriptedGemini,
    StopBeforeNetwork,
)


class _Pick(BaseModel):
    choice: str


@pytest.mark.asyncio
async def test_a_valid_reply_is_parsed_and_accents_survive():
    model = ScriptedGemini.create('{"choice": "Paraná"}')

    result = await llms.resilient_json_output(_Pick, model).ainvoke("q")

    assert result == _Pick(choice="Paraná")


@pytest.mark.asyncio
async def test_gemini_is_asked_for_json_by_mime_type_without_a_schema():
    model = RequestSpyGemini.create()

    with pytest.raises(StopBeforeNetwork):
        await llms.resilient_json_output(_Pick, model).ainvoke("q")

    (request,) = model.requests
    config = request["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is None
    assert config.response_json_schema is None
