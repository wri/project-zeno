"""The generic tool-error funnel (graph.handle_tool_errors).

It is the last-resort safety net for exceptions no tool anticipated, and the
only place standing between a raw driver error and the browser: the returned
ToolMessage is streamed to the client, so it must be marked as an error, name
the tool, and never leak SQL/ORM text.
"""

from types import SimpleNamespace

import pytest
import structlog
from langchain.messages import ToolMessage

from src.agent.graph import handle_tool_errors

pytestmark = pytest.mark.asyncio


def _request(name="add_to_dashboard", args=None):
    return SimpleNamespace(
        tool_call={
            "name": name,
            "id": "call-123",
            "args": args if args is not None else {},
        }
    )


async def test_success_passes_through_untouched():
    sentinel = ToolMessage(content="ok", tool_call_id="call-123")

    async def handler(request):
        return sentinel

    result = await handle_tool_errors.awrap_tool_call(_request(), handler)
    assert result is sentinel


async def test_failure_returns_error_status_and_sanitized_content():
    raw_error = 'relation "dashboard_widgets" does not exist\nSELECT * FROM'

    async def handler(request):
        raise RuntimeError(raw_error)

    result = await handle_tool_errors.awrap_tool_call(_request(), handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.tool_call_id == "call-123"
    # The model sees which tool failed and the exception class...
    assert "add_to_dashboard" in result.content
    assert "RuntimeError" in result.content
    # ...but never the raw driver text.
    assert "dashboard_widgets" not in result.content
    assert "SELECT" not in result.content


async def test_failure_log_carries_tool_name_and_target_ids():
    async def handler(request):
        raise ValueError("boom")

    request = _request(
        args={"dashboard_id": "dash-1", "insight_id": "ins-9", "query": "x"}
    )
    with structlog.testing.capture_logs() as logs:
        await handle_tool_errors.awrap_tool_call(request, handler)

    (record,) = [r for r in logs if r["event"] == "tool_execution_failed"]
    assert record["tool_name"] == "add_to_dashboard"
    assert record["tool_call_id"] == "call-123"
    assert record["dashboard_id"] == "dash-1"
    assert record["insight_id"] == "ins-9"
    # Free-text args are not ids; they stay out of the log fields.
    assert "query" not in record
