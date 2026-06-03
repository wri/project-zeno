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


# --- analytics -------------------------------------------------------------
@pytest.mark.asyncio
async def test_analytics(client, auth_override, superuser_factory):
    su = await superuser_factory("su_an@example.com")
    auth_override(su.id)
    await _seed_trace(
        "a1",
        outcome="ANSWER",
        aoi_type="country",
        user_id="u1",
        session_id="s1",
        latency_seconds=1.0,
        total_cost=0.01,
        turn_tokens=100,
        turn_tool_calls=2,
        tool_error_count=0,
        trace_timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    await _seed_trace(
        "a2",
        outcome="ANSWER",
        aoi_type="state-province",
        user_id="u1",
        session_id="s1",
        latency_seconds=3.0,
        total_cost=0.03,
        turn_tokens=200,
        turn_tool_calls=1,
        tool_error_count=1,
        trace_timestamp=datetime(2026, 6, 1, 2, tzinfo=timezone.utc),
    )
    await _seed_trace(
        "a3",
        outcome="ERROR",
        user_id="u2",
        session_id="s2",
        latency_seconds=2.0,
        total_cost=0.02,
        turn_tokens=0,
        turn_tool_calls=0,
        tool_error_count=0,
        trace_timestamp=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    # the literal /analytics route must not be shadowed by /{trace_id}
    resp = await client.get("/api/traces/analytics", headers=H)
    assert resp.status_code == 200
    b = resp.json()
    assert b["total_traces"] == 3
    assert b["unique_sessions"] == 2
    assert b["unique_users"] == 2
    assert {o["value"]: o["count"] for o in b["outcome_breakdown"]} == {
        "ANSWER": 2,
        "ERROR": 1,
    }
    assert {a["value"]: a["count"] for a in b["aoi_type_breakdown"]} == {
        "country": 1,
        "state-province": 1,
    }
    assert len(b["daily_volume"]) == 2
    assert b["latency"]["avg"] == 2.0
    assert b["cost"]["total"] == 0.06
    assert b["tokens"]["total_turn_tokens"] == 300.0
    assert round(b["tool_usage"]["tool_error_rate"], 2) == 0.33


@pytest.mark.asyncio
async def test_analytics_requires_superuser(client, auth_override, user):
    auth_override(user.id)
    assert (
        await client.get("/api/traces/analytics", headers=H)
    ).status_code == 403


# --- sessions --------------------------------------------------------------
@pytest.mark.asyncio
async def test_sessions(client, auth_override, superuser_factory):
    su = await superuser_factory("su_sess@example.com")
    auth_override(su.id)
    await _seed_trace(
        "sx1",
        session_id="sx",
        user_id="u1",
        prompt="first question",
        trace_timestamp=datetime(2026, 6, 1, 0, tzinfo=timezone.utc),
    )
    await _seed_trace(
        "sx2",
        session_id="sx",
        user_id="u1",
        prompt="second question",
        trace_timestamp=datetime(2026, 6, 1, 1, tzinfo=timezone.utc),
    )
    await _seed_trace(
        "sy1",
        session_id="sy",
        user_id="u2",
        prompt="other thread",
        trace_timestamp=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    b = (await client.get("/api/traces/sessions", headers=H)).json()
    assert b["total"] == 2
    # newest session first (sy at day 2)
    assert b["items"][0]["session_id"] == "sy"
    sx = next(s for s in b["items"] if s["session_id"] == "sx")
    assert sx["turn_count"] == 2
    assert sx["first_prompt"] == "first question"  # earliest turn's prompt
