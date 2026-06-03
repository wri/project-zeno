"""Tests for the superuser-gated Langfuse trace explorer endpoints."""

from datetime import datetime, timezone

import pytest

from src.api.data_models import LangfuseTraceOrm
from tests.conftest import async_session_maker

H = {"Authorization": "Bearer test-token"}


async def _seed_trace(trace_id: str, **kw) -> None:
    raw = kw.pop(
        "raw", {"input": {"messages": []}, "output": {"messages": []}}
    )
    async with async_session_maker() as session:
        session.add(
            LangfuseTraceOrm(id=trace_id, raw=raw, parser_version=1, **kw)
        )
        await session.commit()


# --- auth ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_requires_auth(client):
    assert (await client.get("/api/traces")).status_code == 401


@pytest.mark.asyncio
async def test_list_requires_superuser_not_regular(
    client, auth_override, user
):
    auth_override(user.id)
    assert (await client.get("/api/traces", headers=H)).status_code == 403


# --- list / filter ---------------------------------------------------------
@pytest.mark.asyncio
async def test_list_and_filter(client, auth_override, superuser_factory):
    su = await superuser_factory("su_traces@example.com")
    auth_override(su.id)
    await _seed_trace(
        "t1",
        environment="production",
        outcome="ANSWER",
        user_id="u1",
        session_id="s1",
        prompt="deforestation in Brazil",
        trace_timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    await _seed_trace(
        "t2",
        environment="production",
        outcome="ERROR",
        user_id="u2",
        session_id="s2",
        prompt="forest loss elsewhere",
        trace_timestamp=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    body = (await client.get("/api/traces", headers=H)).json()
    assert body["total"] == 2
    # newest first, and list never leaks raw/output
    assert body["items"][0]["id"] == "t2"
    assert "output" not in body["items"][0]
    assert "raw" not in body["items"][0]

    by_outcome = (
        await client.get("/api/traces?outcome=ANSWER", headers=H)
    ).json()
    assert by_outcome["total"] == 1 and by_outcome["items"][0]["id"] == "t1"

    by_prompt = (
        await client.get("/api/traces?prompt_contains=brazil", headers=H)
    ).json()
    assert by_prompt["total"] == 1 and by_prompt["items"][0]["id"] == "t1"

    by_user = (await client.get("/api/traces?user_id=u2", headers=H)).json()
    assert by_user["total"] == 1 and by_user["items"][0]["id"] == "t2"


@pytest.mark.asyncio
async def test_list_pagination(client, auth_override, superuser_factory):
    su = await superuser_factory("su_page@example.com")
    auth_override(su.id)
    for i in range(5):
        await _seed_trace(
            f"p{i}",
            trace_timestamp=datetime(2026, 6, 1, i, tzinfo=timezone.utc),
        )
    body = (await client.get("/api/traces?limit=2&offset=0", headers=H)).json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] == "p4"  # newest


# --- detail ----------------------------------------------------------------
@pytest.mark.asyncio
async def test_detail_returns_input_output_derived(
    client, auth_override, superuser_factory
):
    su = await superuser_factory("su_detail@example.com")
    auth_override(su.id)
    raw = {
        "input": {"messages": [{"type": "human", "content": "hi"}]},
        "output": {"messages": [], "aoi_selection": {"name": "Brazil"}},
    }
    await _seed_trace(
        "d1",
        outcome="ANSWER",
        answer="the answer",
        raw=raw,
        derived={"aoi_count": 1},
    )
    b = (await client.get("/api/traces/d1", headers=H)).json()
    assert b["answer"] == "the answer"
    assert b["output"]["aoi_selection"]["name"] == "Brazil"
    assert b["input"]["messages"][0]["content"] == "hi"
    assert b["derived"]["aoi_count"] == 1


@pytest.mark.asyncio
async def test_detail_404(client, auth_override, superuser_factory):
    su = await superuser_factory("su_404@example.com")
    auth_override(su.id)
    assert (await client.get("/api/traces/nope", headers=H)).status_code == 404
