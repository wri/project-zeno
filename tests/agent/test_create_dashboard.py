"""Tests for the create_dashboard agent tool."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agent.tools.create_dashboard import create_dashboard
from src.shared.request_context import bound_user_id


def _content(command):
    return command.update["messages"][0].content


def _state(aois=None, name="Paraná"):
    if aois is None:
        aois = [
            {
                "source": "gadm",
                "src_id": "BRA.16_1",
                "subtype": "state-province",
                "name": "Paraná",
                "bbox": [-54.6, -26.7, -48.0, -22.5],
            }
        ]
    return {"aoi_selection": {"name": name, "aois": aois}}


async def test_create_dashboard_from_state_aoi():
    create = AsyncMock(return_value="dash-1")
    with (
        patch(
            "src.api.repositories.dashboard_writer.create_dashboard", create
        ),
        bound_user_id("user-1"),
    ):
        command = await create_dashboard.coroutine(
            state=_state(), tool_call_id="t1"
        )

    # Dashboard id lands in state and in the frontend refetch signal.
    assert command.update["dashboard_id"] == "dash-1"
    message = command.update["messages"][0]
    assert message.status == "success"
    assert message.response_metadata == {
        "msg_type": "dashboard_updated",
        "dashboard_id": "dash-1",
    }
    assert "Paraná" in message.content

    # Only the reference fields are persisted — no bbox, no geometry.
    create.assert_awaited_once_with(
        user_id="user-1",
        name="Paraná",
        aois=[
            {
                "source": "gadm",
                "src_id": "BRA.16_1",
                "subtype": "state-province",
                "name": "Paraná",
            }
        ],
    )


async def test_create_dashboard_explicit_name():
    create = AsyncMock(return_value="dash-1")
    with (
        patch(
            "src.api.repositories.dashboard_writer.create_dashboard", create
        ),
        bound_user_id("user-1"),
    ):
        await create_dashboard.coroutine(
            name="Forest monitoring", state=_state(), tool_call_id="t1"
        )
    assert create.await_args.kwargs["name"] == "Forest monitoring"


async def test_create_dashboard_raises_without_user():
    """A missing identity means the request context channel broke — every
    entry point binds a user — so the tool raises (into the generic error
    funnel) instead of degrading into a misleading permission error."""
    with pytest.raises(RuntimeError, match="without an authenticated user"):
        await create_dashboard.coroutine(state=_state(), tool_call_id="t1")


async def test_create_dashboard_requires_aoi():
    with bound_user_id("user-1"):
        command = await create_dashboard.coroutine(state={}, tool_call_id="t1")
    assert command.update["messages"][0].status == "error"
    assert "No area selected" in _content(command)


async def test_create_dashboard_rejects_multi_aoi_selection():
    aois = [
        {
            "source": "gadm",
            "src_id": "BRA",
            "subtype": "country",
            "name": "Brazil",
        },
        {
            "source": "gadm",
            "src_id": "ARG",
            "subtype": "country",
            "name": "Argentina",
        },
    ]
    with bound_user_id("user-1"):
        command = await create_dashboard.coroutine(
            state=_state(aois=aois, name="Brazil and Argentina"),
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "single area" in _content(command)
