"""What InsightTextGenerator actually sends to Gemini, and gets back.

PZB-1243: the text stage asks for JSON by mime type, with no response
schema, so its system prompt has to spell out the keys itself.
"""

import pytest

from src.agent.llms import json_reply_instruction
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.text_generator import (
    InsightText,
    InsightTextGenerator,
)
from tests.unit.agent.fake_gemini import (
    RequestSpyGemini,
    ScriptedGemini,
    StopBeforeNetwork,
)

CHARTS = [
    InsightChart(
        position=0,
        title="Annual loss",
        chart_type="bar",
        x_axis="year",
        y_axis="area_ha",
        chart_data=[{"year": 2020, "area_ha": 1234.5}],
    )
]
DATASET = {"cautions": "Tree cover loss is not deforestation."}


async def _captured_request(language="pt") -> dict:
    """Run the text stage against a spy and return the request it built."""
    model = RequestSpyGemini.create()
    with pytest.raises(StopBeforeNetwork):
        await InsightTextGenerator(model).generate(
            CHARTS, DATASET, "Loss in Piauí?", language=language
        )
    (request,) = model.requests
    return request


def _system_prompt(request: dict) -> str:
    parts = request["config"].system_instruction.parts
    return "".join(part.text for part in parts)


@pytest.mark.asyncio
async def test_a_reply_round_trips_through_the_text_stage():
    model = ScriptedGemini.create(
        '{"primary_insight": "Piauí lost 5% of its cover.",'
        ' "follow_up_suggestions": ["Compare with Maranhão"]}'
    )

    result = await InsightTextGenerator(model).generate(
        CHARTS, DATASET, "Loss in Piauí?", language="pt"
    )

    assert result == InsightText(
        primary_insight="Piauí lost 5% of its cover.",
        follow_up_suggestions=["Compare with Maranhão"],
    )


@pytest.mark.asyncio
async def test_system_prompt_spells_out_the_json_keys_and_language():
    system = _system_prompt(await _captured_request(language="pt"))

    assert json_reply_instruction(InsightText) in system
    assert "Português" in system


@pytest.mark.asyncio
async def test_text_stage_sends_no_response_schema():
    config = (await _captured_request())["config"]

    assert config.response_mime_type == "application/json"
    assert config.response_schema is None
    assert config.response_json_schema is None
