"""The nudge before a window change is enforced, not just instructed.

Moving a monitoring section to a new window replaces every figure the user
is looking at, and the previous ones are deleted. A prompt telling the model
to ask first is a hope; refusing to act without `confirmed=True` is a rule.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.tools.update_nrt_monitoring_section import (
    update_nrt_monitoring_section,
)
from src.shared.request_context import bound_user_id


def _section(title="Recent disturbance", type="nrt-monitoring", **config):
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        type=type,
        config=config
        or {"days": 14, "start_date": "2026-08-20", "end_date": "2026-09-03"},
    )


def _dashboard(*sections, aois=True):
    return SimpleNamespace(
        id=uuid4(),
        name="Genève",
        sections=list(sections),
        aois=[
            SimpleNamespace(
                source="gadm",
                src_id="CHE.8_1",
                subtype="state-province",
                name="Genève",
            )
        ]
        if aois
        else [],
    )


def _content(command):
    (message,) = command.update["messages"]
    return message.content


async def _call(dashboard, **kwargs):
    kwargs.setdefault("days", 90)
    kwargs.setdefault("state", {"dashboard_id": str(dashboard.id)})
    with patch(
        "src.agent.tools.update_nrt_monitoring_section."
        "load_editable_dashboard",
        AsyncMock(return_value=dashboard),
    ):
        with bound_user_id("user-1"):
            # .coroutine bypasses the injected-argument plumbing, as the
            # other dashboard tool tests do.
            return await update_nrt_monitoring_section.coroutine(
                **kwargs, tool_call_id="call-1"
            )


@pytest.mark.asyncio
async def test_unconfirmed_change_does_nothing_and_asks():
    dashboard = _dashboard(_section())

    with patch(
        "src.agent.tools.update_nrt_monitoring_section.refresh_nrt_section",
        AsyncMock(),
    ) as refresh:
        command = await _call(dashboard)

    refresh.assert_not_called()
    body = _content(command)
    assert "send_nudge" in body
    assert "time_range_choice" in body
    # It states what is on screen now, so the model can offer real options.
    assert "2026-08-20" in body and "2026-09-03" in body


@pytest.mark.asyncio
async def test_confirmed_change_applies():
    dashboard = _dashboard(_section())
    result = SimpleNamespace(
        section_id="sec-1",
        insight_id="ins-1",
        widget_ids=["w1", "w2", "w3"],
        start_date="2026-06-05",
        end_date="2026-09-03",
        days=90,
        warnings=[],
    )

    with patch(
        "src.agent.tools.update_nrt_monitoring_section.refresh_nrt_section",
        AsyncMock(return_value=result),
    ) as refresh:
        command = await _call(dashboard, confirmed=True)

    refresh.assert_awaited_once()
    assert refresh.await_args.kwargs["days"] == 90
    assert "2026-06-05" in _content(command)
    assert command.update["dashboard_id"] == str(dashboard.id)


@pytest.mark.asyncio
async def test_out_of_range_window_refused_before_anything_else():
    dashboard = _dashboard(_section())

    with patch(
        "src.agent.tools.update_nrt_monitoring_section.refresh_nrt_section",
        AsyncMock(),
    ) as refresh:
        command = await _call(dashboard, days=400, confirmed=True)

    refresh.assert_not_called()
    assert "between 1 and 365" in _content(command)


@pytest.mark.asyncio
async def test_two_monitoring_sections_must_be_named():
    dashboard = _dashboard(
        _section(title="Alerts, August"), _section(title="Alerts, July")
    )

    command = await _call(dashboard, confirmed=True)

    body = _content(command)
    assert "more than one monitoring section" in body
    assert "Alerts, August" in body and "Alerts, July" in body


@pytest.mark.asyncio
async def test_dashboard_without_a_monitoring_section():
    dashboard = _dashboard(_section(type="default"))

    command = await _call(dashboard, confirmed=True)

    assert "add_nrt_monitoring_section" in _content(command)
