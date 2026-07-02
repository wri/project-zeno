"""Tests for the add_to_dashboard agent tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import structlog

from src.agent.tools.add_to_dashboard import add_to_dashboard


def _content(command):
    return command.update["messages"][0].content


def _dashboard(user_id="user-1", name="Paraná"):
    return SimpleNamespace(
        id=uuid4(), user_id=user_id, name=name, is_public=False
    )


def _insight(user_id="user-1"):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        is_public=False,
        insight_text="Tree cover loss rose 12%.",
    )


def _patches(dashboard, insight, widget_id="widget-1"):
    return (
        patch(
            "src.api.repositories.dashboard_writer.get_dashboard",
            new=AsyncMock(return_value=dashboard),
        ),
        patch(
            "src.agent.tools.add_to_dashboard._load_visible_insight",
            new=AsyncMock(return_value=insight),
        ),
        patch(
            "src.api.repositories.dashboard_writer.add_widget",
            new=AsyncMock(return_value=widget_id),
        ),
    )


async def test_add_to_dashboard_defaults_from_state():
    dashboard = _dashboard()
    insight = _insight()
    get_dash, load_insight, add_widget = _patches(dashboard, insight)
    state = {
        "insight_id": str(insight.id),
        "dashboard_id": str(dashboard.id),
    }
    with (
        get_dash,
        load_insight,
        add_widget as add_widget_mock,
        structlog.contextvars.bound_contextvars(user_id="user-1"),
    ):
        command = await add_to_dashboard.coroutine(
            state=state, tool_call_id="t1"
        )

    message = command.update["messages"][0]
    assert message.status == "success"
    assert message.response_metadata == {
        "msg_type": "dashboard_updated",
        "dashboard_id": str(dashboard.id),
    }
    assert command.update["dashboard_id"] == str(dashboard.id)
    add_widget_mock.assert_awaited_once_with(
        str(dashboard.id),
        widget_type="insight",
        insight_id=str(insight.id),
    )


async def test_add_to_dashboard_falls_back_to_view_context():
    dashboard = _dashboard()
    insight = _insight()
    get_dash, load_insight, add_widget = _patches(dashboard, insight)
    state = {
        "insight_id": str(insight.id),
        "view_context": {
            "page": "dashboard",
            "dashboard_id": str(dashboard.id),
        },
    }
    with (
        get_dash,
        load_insight,
        add_widget,
        structlog.contextvars.bound_contextvars(user_id="user-1"),
    ):
        command = await add_to_dashboard.coroutine(
            state=state, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "success"
    assert command.update["dashboard_id"] == str(dashboard.id)


async def test_add_to_dashboard_requires_insight():
    with structlog.contextvars.bound_contextvars(user_id="user-1"):
        command = await add_to_dashboard.coroutine(
            dashboard_id=str(uuid4()), state={}, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "error"
    assert "No insight to add" in _content(command)


async def test_add_to_dashboard_requires_dashboard():
    with structlog.contextvars.bound_contextvars(user_id="user-1"):
        command = await add_to_dashboard.coroutine(
            insight_id=str(uuid4()), state={}, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "error"
    assert "No dashboard to add to" in _content(command)


async def test_add_to_dashboard_owner_only():
    # A public dashboard someone else owns is readable but not editable.
    dashboard = _dashboard(user_id="someone-else")
    dashboard.is_public = True
    insight = _insight()
    get_dash, load_insight, add_widget = _patches(dashboard, insight)
    with (
        get_dash,
        load_insight,
        add_widget as add_widget_mock,
        structlog.contextvars.bound_contextvars(user_id="user-1"),
    ):
        command = await add_to_dashboard.coroutine(
            insight_id=str(insight.id),
            dashboard_id=str(dashboard.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "not found or not editable" in _content(command)
    add_widget_mock.assert_not_awaited()


async def test_add_to_dashboard_insight_must_be_visible():
    dashboard = _dashboard()
    get_dash, load_insight, add_widget = _patches(dashboard, insight=None)
    with (
        get_dash,
        load_insight,
        add_widget as add_widget_mock,
        structlog.contextvars.bound_contextvars(user_id="user-1"),
    ):
        command = await add_to_dashboard.coroutine(
            insight_id=str(uuid4()),
            dashboard_id=str(dashboard.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "not found or not accessible" in _content(command)
    add_widget_mock.assert_not_awaited()
