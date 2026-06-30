"""Tests for the update_insight_display tool and its merge logic."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.display_reviser import (
    RevisedChart,
    RevisedInsight,
)
from src.agent.tools.update_insight_display import (
    _apply_revision,
    update_insight_display,
)


def _content(command):
    return command.update["messages"][0].content


def _original_chart():
    return InsightChart(
        position=0,
        title="Old title",
        chart_type="bar",
        x_axis="year",
        y_axis="loss",
        chart_data=[{"year": 2020, "loss": 5, "gain": 2}],
    )


def _fake_orm_row(**kwargs):
    """Object shaped like InsightOrm (+ chart rows) for the load path."""
    defaults = dict(
        id=uuid4(),
        user_id="user-1",
        insight_text="Old summary.",
        follow_up_suggestions=["old follow-up"],
        charts=[
            SimpleNamespace(
                position=0,
                title="Old title",
                chart_type="bar",
                x_axis="year",
                y_axis="loss",
                color_field="",
                stack_field="",
                group_field="",
                series_fields=[],
                chart_data=[{"year": 2020, "loss": 5, "gain": 2}],
            )
        ],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_apply_revision_restyles_and_keeps_data():
    revised = RevisedInsight(
        primary_insight="New summary",
        follow_up_suggestions=["f1"],
        charts=[
            RevisedChart(
                position=0,
                title="New title",
                chart_type="line",
                x_axis="year",
                y_axis="gain",  # different but existing column
            )
        ],
    )
    out = _apply_revision([_original_chart()], revised)
    chart = out.charts[0]
    assert out.primary_insight == "New summary"
    assert out.follow_up_suggestions == ["f1"]
    assert chart.title == "New title"
    assert chart.chart_type == "line"
    assert chart.y_axis == "gain"
    # Underlying rows are untouched (no new data).
    assert chart.chart_data == [{"year": 2020, "loss": 5, "gain": 2}]
    # stamp_insight copies the primary onto each chart.
    assert chart.insight == "New summary"


def test_apply_revision_drops_unknown_columns():
    revised = RevisedInsight(
        primary_insight="x",
        follow_up_suggestions=["f"],
        charts=[
            RevisedChart(
                position=0,
                title="Bad",
                chart_type="bar",
                x_axis="year",
                y_axis="does_not_exist",
            )
        ],
    )
    out = _apply_revision([_original_chart()], revised)
    # Original chart is preserved untouched rather than producing a broken one.
    assert out.charts[0].title == "Old title"
    assert out.charts[0].y_axis == "loss"


@pytest.mark.asyncio
async def test_update_insight_display_no_target_errors():
    command = await update_insight_display.coroutine(
        instruction="make it a line chart", state={}, tool_call_id="t1"
    )
    assert command.update["messages"][0].status == "error"
    assert "No insight to update" in _content(command)


@pytest.mark.asyncio
async def test_update_insight_display_not_editable_errors():
    with patch(
        "src.agent.tools.update_insight_display._load_editable_insight",
        new=AsyncMock(return_value=None),
    ):
        command = await update_insight_display.coroutine(
            instruction="rename it",
            insight_id=str(uuid4()),
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "not found or not editable" in _content(command)


@pytest.mark.asyncio
async def test_update_insight_display_happy_path():
    row = _fake_orm_row()
    revised = RevisedInsight(
        primary_insight="New summary",
        follow_up_suggestions=["f1"],
        charts=[
            RevisedChart(
                position=0, title="New title", chart_type="line", y_axis="gain"
            )
        ],
    )
    with (
        patch(
            "src.agent.tools.update_insight_display._load_editable_insight",
            new=AsyncMock(return_value=row),
        ),
        patch(
            "src.agent.tools.update_insight_display.InsightDisplayReviser.revise",
            new=AsyncMock(return_value=revised),
        ),
        patch(
            "src.agent.tools.update_insight_display.update_insight",
            new=AsyncMock(return_value=True),
        ) as mock_update,
    ):
        command = await update_insight_display.coroutine(
            instruction="change to a line chart and reword",
            state={"insight_id": str(row.id)},
            tool_call_id="t1",
        )

    assert command.update["insight"] == "New summary"
    assert command.update["follow_up_suggestions"] == ["f1"]
    charts_data = command.update["charts_data"]
    assert charts_data[0]["title"] == "New title"
    assert charts_data[0]["type"] == "line"
    # Persisted in place under the same id.
    persisted_id, persisted_insight = mock_update.call_args.args
    assert persisted_id == str(row.id)
    assert persisted_insight.primary_insight == "New summary"
    # Distinct signal so the frontend replaces the insight in place.
    message = command.update["messages"][0]
    assert message.status == "success"
    assert message.response_metadata["msg_type"] == "insight_updated"
    assert message.response_metadata["insight_id"] == str(row.id)
