"""Tests for the generated title and description of a monitoring section.

The generator is the last step of a build whose data is already gathered, so
what matters most here is that it never takes the section down with it.
"""

import pytest
from langchain_core.runnables import RunnableLambda

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.nrt_summary import (
    TITLE_MAX_CHARS,
    SectionSummary,
    _rounded,
    fallback_summary,
    generate_section_summary,
)

CHARTS = [
    InsightChart(
        position=0,
        title="Disturbance alerts by confidence",
        chart_type="line",
        x_axis="month",
        y_axis="area_ha",
        color_field="alert_confidence",
        chart_data=[
            {
                "month": "2026-07",
                "alert_confidence": "high",
                "area_ha": 120.5,
            }
        ],
    )
]

PERIOD = {"start_date": "2026-06-04", "end_date": "2026-09-02"}


class _FakeModel:
    """A model whose structured output is fixed, or which raises.

    The generator composes ``_PROMPT | model.with_structured_output(...)``,
    so the stand-in has to be a real runnable — hence RunnableLambda rather
    than a mock.
    """

    def __init__(self, result):
        self._result = result
        self.calls = 0

    def with_structured_output(self, _schema):
        def _invoke(_inputs):
            self.calls += 1
            if isinstance(self._result, Exception):
                raise self._result
            return self._result

        return RunnableLambda(_invoke)


@pytest.mark.asyncio
async def test_uses_the_model_output():
    summary = SectionSummary(
        title="Alerts in Paraná, last 90 days",
        description="120.5 ha of high-confidence alerts.",
    )
    result = await generate_section_summary(
        CHARTS, aoi_name="Paraná", **PERIOD, model=_FakeModel(summary)
    )

    assert result.title == "Alerts in Paraná, last 90 days"
    assert result.description == "120.5 ha of high-confidence alerts."


@pytest.mark.asyncio
async def test_model_failure_falls_back_instead_of_raising():
    result = await generate_section_summary(
        CHARTS,
        aoi_name="Paraná",
        **PERIOD,
        model=_FakeModel(RuntimeError("model unavailable")),
    )

    assert result == fallback_summary("Paraná", **PERIOD)
    assert "Paraná" in result.title


@pytest.mark.asyncio
async def test_blank_model_output_falls_back():
    result = await generate_section_summary(
        CHARTS,
        aoi_name="Paraná",
        **PERIOD,
        model=_FakeModel(SectionSummary(title="  ", description="  ")),
    )

    assert result == fallback_summary("Paraná", **PERIOD)


@pytest.mark.asyncio
async def test_no_charts_skips_the_model_entirely():
    model = _FakeModel(SectionSummary(title="unused", description="unused"))
    result = await generate_section_summary(
        [], aoi_name="Paraná", **PERIOD, model=model
    )

    assert model.calls == 0
    assert result == fallback_summary("Paraná", **PERIOD)


@pytest.mark.asyncio
async def test_overlong_title_is_trimmed():
    result = await generate_section_summary(
        CHARTS,
        aoi_name="Paraná",
        **PERIOD,
        model=_FakeModel(
            SectionSummary(title="A" * 200, description="Some text.")
        ),
    )

    assert len(result.title) == TITLE_MAX_CHARS


def test_fallback_states_the_period_and_the_caveat():
    summary = fallback_summary("Paraná", "2026-06-04", "2026-09-02")

    assert "2026-06-04" in summary.description
    assert "2026-09-02" in summary.description
    assert "potential disturbance" in summary.description


def test_prompt_sees_rounded_figures_but_the_chart_keeps_precision():
    """Analytics areas arrive at full float precision, and a model told to
    quote a figure exactly will write "153409.28893796972 ha"."""
    chart = InsightChart(
        position=0,
        title="Alerts",
        chart_type="line",
        x_axis="month",
        y_axis="area_ha",
        chart_data=[
            {"month": "2026-07", "area_ha": 153409.28893796972},
            {"month": "2026-08", "area_ha": 15.0812345},
        ],
    )

    rounded = _rounded(chart)

    assert [row["area_ha"] for row in rounded.chart_data] == [153409, 15.1]
    # The stored chart is untouched: only the prompt copy is rounded.
    assert chart.chart_data[0]["area_ha"] == 153409.28893796972


def test_rounding_leaves_non_numeric_columns_alone():
    chart = InsightChart(
        position=0,
        title="Alerts",
        chart_type="line",
        x_axis="month",
        y_axis="area_ha",
        color_field="alert_confidence",
        chart_data=[
            {"month": "2026-07", "alert_confidence": "high", "area_ha": 1.234}
        ],
    )

    (row,) = _rounded(chart).chart_data

    assert row["month"] == "2026-07"
    assert row["alert_confidence"] == "high"
    assert row["area_ha"] == 1.2
