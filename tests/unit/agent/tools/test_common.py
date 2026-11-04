"""require_current_user_id — the identity read for authorization in tools.

Every entry point binds a user id (chat requires auth, the CLI binds a
default), so an unbound identity inside a tool means the request-context
channel broke. The helper must fail loudly — raise into the tool-error
funnel — and leave a searchable log event, never degrade silently.
"""

import pytest
import structlog

from src.agent.subagents.analyst.charts.model import Insight
from src.agent.tools.common import (
    insight_updated_command,
    require_current_user_id,
)
from src.shared.request_context import bound_user_id


def test_returns_bound_user_id():
    with bound_user_id("user-42"):
        assert require_current_user_id("search_insights") == "user-42"


def test_raises_and_logs_when_unbound():
    with bound_user_id(None):
        with structlog.testing.capture_logs() as logs:
            with pytest.raises(
                RuntimeError, match="without an authenticated user"
            ):
                require_current_user_id("search_insights")

    (record,) = [
        r for r in logs if r["event"] == "tool_invoked_without_identity"
    ]
    assert record["tool_name"] == "search_insights"
    assert record["log_level"] == "error"


def test_a_recalled_insight_without_inputs_writes_null_to_state():
    """An insight saved before inputs were recorded must clear the inputs of
    the insight on screen before it, not leave them in state."""
    command = insight_updated_command(
        "insight-1",
        Insight(charts=[], primary_insight="Old."),
        "Found it.",
        "call-1",
        analysis_inputs=None,
    )
    assert command.update["insight_id"] == "insight-1"
    assert "analysis_inputs" in command.update
    assert command.update["analysis_inputs"] is None
