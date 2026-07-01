"""Tests for the inspect_view_context agent tool and the view breadcrumb."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from src.agent.middleware import format_session_block
from src.agent.tools.inspect_view_context import (
    _chart_variables,
    _extract_insight_ids,
    format_insights,
    format_view_context,
    inspect_view_context,
)

VIEW_STATE = {
    "view_context": {
        "page": "report",
        "viewport": {"bbox": [-74, -34, -34, 5], "zoom": 5},
        "visible_layers": [
            {"id": "tree-cover", "name": "Tree cover"},
            {"id": "fire-alerts", "name": "Fire alerts"},
        ],
        "visible_aois": [
            {"source": "gadm", "src_id": "BRA.24_1", "name": "São Paulo"}
        ],
        "selected_basemap": "satellite",
    }
}


def _content(command):
    return command.update["messages"][0].content


def _fake_insight(**kwargs):
    """Build an object shaped like InsightOrm (+ charts) for formatting tests."""
    defaults = dict(
        id=uuid4(),
        insight_text="Tree cover loss rose 12% over the period.",
        follow_up_suggestions=["Compare to fires", "Break down by driver"],
        is_public=False,
        user_id="user-1",
        created_at=datetime(2026, 6, 1),
        charts=[
            SimpleNamespace(
                title="Annual tree cover loss",
                chart_type="bar",
                x_axis="year",
                y_axis="loss_ha",
                color_field="",
                stack_field="",
                group_field="",
                series_fields=[],
                chart_data=[{"year": 2020}, {"year": 2021}],
            )
        ],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_inspect_view_context_returns_snapshot():
    command = await inspect_view_context.coroutine(
        state=VIEW_STATE, tool_call_id="t1"
    )
    content = _content(command)
    assert "Page: report" in content
    assert "Tree cover" in content
    assert "Fire alerts" in content
    assert "São Paulo" in content
    # Unknown keys are surfaced, not dropped.
    assert "selected_basemap" in content


@pytest.mark.asyncio
async def test_inspect_view_context_handles_missing_state():
    command = await inspect_view_context.coroutine(state={}, tool_call_id="t1")
    assert "No frontend view context" in _content(command)


def test_format_view_context_empty():
    assert "No frontend view context" in format_view_context({})


def test_breadcrumb_present_with_view_context():
    block = format_session_block(VIEW_STATE)
    assert "View: report page · 2 layer(s) · 1 AOI(s) visible" in block
    assert "call inspect_view_context for details" in block
    # The bulky detail (exact viewport, layer ids) stays out of the prompt.
    assert "BRA.24_1" not in block


def test_breadcrumb_none_without_view_context():
    assert "View: none" in format_session_block({})


def test_breadcrumb_includes_insight_count():
    state = {"view_context": {"page": "report", "visible_insights": [{}, {}]}}
    assert "2 insight(s) on screen" in format_session_block(state)


def test_extract_insight_ids_parses_dicts_strings_and_skips_bad():
    good = uuid4()
    refs = [{"id": str(good)}, str(uuid4()), {"id": None}, "not-a-uuid"]
    ids = _extract_insight_ids(refs)
    assert good in ids
    assert all(isinstance(i, UUID) for i in ids)
    assert len(ids) == 2  # the None and the bad string are skipped


def test_chart_variables_lists_only_populated_fields():
    chart = SimpleNamespace(
        x_axis="year",
        y_axis="loss_ha",
        color_field="driver",
        stack_field="",
        group_field="",
        series_fields=[],
    )
    out = _chart_variables(chart)
    assert "x=year" in out and "y=loss_ha" in out and "color=driver" in out
    assert "stack=" not in out


def test_format_insights_prints_key_content():
    out = format_insights([_fake_insight()])
    assert "Summary: Tree cover loss rose 12%" in out
    assert 'Chart "Annual tree cover loss" (bar)' in out
    assert "x=year, y=loss_ha" in out
    assert "2 data point(s)" in out
    assert "Follow-ups: Compare to fires; Break down by driver" in out


@pytest.mark.asyncio
async def test_inspect_view_context_loads_insights():
    insight = _fake_insight()
    view = {
        "view_context": {
            "page": "report",
            "visible_insights": [{"id": str(insight.id)}],
        }
    }
    with patch(
        "src.agent.tools.inspect_view_context._load_insights",
        new=AsyncMock(return_value=[insight]),
    ):
        command = await inspect_view_context.coroutine(
            state=view, tool_call_id="t1"
        )
    content = _content(command)
    assert "Visible insights: 1" in content
    assert "Annual tree cover loss" in content
    assert "Summary: Tree cover loss rose 12%" in content


@pytest.mark.asyncio
async def test_inspect_view_context_insight_load_empty():
    view = {"view_context": {"visible_insights": [{"id": str(uuid4())}]}}
    with patch(
        "src.agent.tools.inspect_view_context._load_insights",
        new=AsyncMock(return_value=[]),
    ):
        command = await inspect_view_context.coroutine(
            state=view, tool_call_id="t1"
        )
    assert "none could be loaded" in _content(command)
