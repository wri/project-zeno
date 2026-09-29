"""Tests for the generated title and description of a template section."""

import pytest
from langchain_core.runnables import RunnableLambda

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.analysis_templates.registry import get_template
from src.api.services.analysis_templates.text import (
    TITLE_MAX_CHARS,
    SectionText,
    generate_section_text,
)

NRT = get_template("nrt-monitoring")
CHARTS = [
    InsightChart(
        title="Alerts by confidence",
        chart_type="line",
        x_axis="alert_date",
        y_axis="area_ha",
        color_field="alert_confidence",
        chart_data=[
            {
                "alert_date": "2026-09-14",
                "alert_confidence": "high",
                "area_ha": 12.3456789,
            },
            {
                "alert_date": "2026-09-15",
                "alert_confidence": "high",
                "area_ha": 153409.28893796972,
            },
        ],
    )
]


class _FakeModel:
    """A model with a fixed structured output, or one that raises. The
    prompt pipes into ``with_structured_output``, so the stand-in must be a
    runnable."""

    def __init__(self, result):
        self._result = result
        self.inputs = None

    def with_structured_output(self, _schema):
        def _invoke(prompt_value):
            self.inputs = prompt_value.to_string()
            if isinstance(self._result, Exception):
                raise self._result
            return self._result

        return RunnableLambda(_invoke)


async def _generate(model, language="en"):
    return await generate_section_text(
        NRT,
        aoi_name="Paraná",
        start_date="2026-09-09",
        end_date="2026-09-23",
        widget_summaries=["chart: Integrated alerts", "map layer"],
        charts=CHARTS,
        language=language,
        model=model,
    )


@pytest.mark.asyncio
async def test_uses_the_model_output():
    model = _FakeModel(
        SectionText(
            title="Recent alerts in Paraná.",
            description="12.3 ha of high-confidence alerts.",
        )
    )

    title, description = await _generate(model)

    assert title == "Recent alerts in Paraná"
    assert description == "12.3 ha of high-confidence alerts."


@pytest.mark.asyncio
async def test_prompt_has_rounded_numbers_purpose_and_rules():
    model = _FakeModel(SectionText(title="T", description="D"))

    await _generate(model)

    assert "12.3" in model.inputs
    assert "12.3456789" not in model.inputs
    assert "153409" in model.inputs
    assert "153409.28" not in model.inputs
    assert NRT.purpose in model.inputs
    assert "- map layer" in model.inputs
    assert "not confirmed" in model.inputs  # the alerts presentation rules


@pytest.mark.asyncio
async def test_stored_chart_keeps_full_precision():
    await _generate(_FakeModel(SectionText(title="T", description="D")))

    assert CHARTS[0].chart_data[0]["area_ha"] == 12.3456789


@pytest.mark.asyncio
async def test_model_error_falls_back():
    title, description = await _generate(_FakeModel(RuntimeError("down")))

    assert title == "Recent disturbance alerts in Paraná"
    assert "2026-09-09" in description and "2026-09-23" in description


@pytest.mark.asyncio
async def test_empty_output_falls_back():
    title, _ = await _generate(
        _FakeModel(SectionText(title=" ", description="D"))
    )

    assert title == "Recent disturbance alerts in Paraná"


@pytest.mark.asyncio
async def test_fallback_is_in_the_user_language():
    title, _ = await _generate(_FakeModel(RuntimeError("down")), "es")

    assert title == "Alertas de perturbación recientes en Paraná"


@pytest.mark.asyncio
async def test_title_is_cut_to_the_limit():
    model = _FakeModel(SectionText(title="x" * 100, description="D"))

    title, _ = await _generate(model)

    assert len(title) == TITLE_MAX_CHARS
