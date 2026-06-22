"""Tests for the inspect_view_context agent tool and the view breadcrumb."""

import pytest

from src.agent.middleware import format_session_block
from src.agent.tools.inspect_view_context import (
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
