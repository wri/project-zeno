"""Unit tests for the canonical InsightChart/Insight seam model."""

import json
import math

import pytest

from src.agent.subagents.analyst.charts.model import (
    Insight,
    InsightChart,
)
from src.agent.subagents.analyst.code_executors.base import ChartInsight

# The exact camelCase keys the frontend `charts_data` consumes today.
FRONTEND_KEYS = {
    "id",
    "title",
    "type",
    "insight",
    "data",
    "xAxis",
    "yAxis",
    "colorField",
    "stackField",
    "groupField",
    "seriesFields",
}


def _sample_chart() -> InsightChart:
    return InsightChart(
        position=1,
        title="Annual Loss",
        chart_type="bar",
        x_axis="year",
        y_axis="area_ha",
        chart_data=[{"year": 2020, "area_ha": 5.0}],
    )


def test_to_frontend_dict_has_exact_legacy_keys():
    fe = _sample_chart().to_frontend_dict()
    assert set(fe.keys()) == FRONTEND_KEYS
    assert fe["id"] == "chart_1"
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "year"
    assert fe["data"] == [{"year": 2020, "area_ha": 5.0}]


def test_to_orm_kwargs_is_snake_case_and_complete():
    kwargs = _sample_chart().to_orm_kwargs()
    assert set(kwargs.keys()) == {
        "position",
        "title",
        "chart_type",
        "x_axis",
        "y_axis",
        "color_field",
        "stack_field",
        "group_field",
        "series_fields",
        "chart_data",
    }
    assert kwargs["chart_type"] == "bar"
    assert kwargs["y_axis"] == "area_ha"


def test_from_chart_insight_carries_spec_and_data():
    ci = ChartInsight(
        title="Multi",
        chart_type="stacked-bar",
        x_axis="year",
        series_fields=["a", "b"],
    )
    rows = [{"year": 2020, "a": 1, "b": 2}]
    chart = InsightChart.from_chart_insight(ci, rows, position=3)
    assert chart.position == 3
    assert chart.chart_type == "stacked-bar"
    assert chart.series_fields == ["a", "b"]
    assert chart.chart_data == rows


def test_chart_data_nan_is_sanitized_to_none():
    # pandas to_dict() emits float('nan') for missing cells; these are not valid
    # JSONB tokens and must be scrubbed before persistence. The failing payload
    # had NaN in both value and key positions.
    chart = InsightChart(
        title="Disturbance",
        chart_type="pie",
        x_axis="name",
        chart_data=[
            {"name": "forest", "value": 540.0},
            {"name": float("nan"), "value": float("nan")},
            {"name": "infra", "value": float("inf")},
        ],
    )
    assert chart.chart_data == [
        {"name": "forest", "value": 540.0},
        {"name": None, "value": None},
        {"name": "infra", "value": None},
    ]
    # The sanitized rows must survive a strict (NaN-rejecting) JSON dump,
    # which is what the Postgres JSONB parser does.
    json.dumps(chart.to_orm_kwargs()["chart_data"], allow_nan=False)
    assert not any(
        isinstance(v, float) and not math.isfinite(v)
        for row in chart.chart_data
        for v in row.values()
    )


def test_axis_validator_rejects_missing_axis():
    with pytest.raises(ValueError):
        InsightChart(title="bad", chart_type="bar", x_axis="year")


def test_axis_validator_allows_pie_without_axis():
    chart = InsightChart(title="ok", chart_type="pie", x_axis="name")
    assert chart.chart_type == "pie"


def test_stamp_insight_copies_text_to_each_chart():
    insight = Insight(
        charts=[_sample_chart(), _sample_chart()],
        primary_insight="Loss increased.",
        follow_up_suggestions=["Compare regions."],
    ).stamp_insight()
    assert all(c.insight == "Loss increased." for c in insight.charts)
    assert insight.charts[0].to_frontend_dict()["insight"] == "Loss increased."
