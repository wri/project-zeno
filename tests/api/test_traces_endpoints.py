"""Tests for the superuser-gated Langfuse trace explorer endpoints."""

from datetime import datetime, timezone

import pytest
from fastapi import Request
from sqlalchemy import select

from src.api.app import app
from src.api.auth.dependencies import fetch_user_from_rw_api
from src.api.auth.scopes import TRACES_READ
from src.api.data_models import LangfuseTraceOrm
from src.api.schemas import UserModel
from src.api.services.langfuse.ingest import recompute_turn_positions
from tests.conftest import async_session_maker

H = {"Authorization": "Bearer test-token"}


@pytest.fixture
def machine_auth_override():
    """Override auth with a machine identity carrying the given scopes (set on
    request.state, as validate_machine_user_token does for a real key)."""
    original = app.dependency_overrides.get(fetch_user_from_rw_api)

    def _set(scopes, user_id="machine-traces"):
        async def _dep(request: Request):
            request.state.token_scopes = list(scopes)
            return UserModel.model_validate(
                {
                    "id": user_id,
                    "name": user_id,
                    "email": f"{user_id}@example.com",
                    "user_type": "machine",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                }
            )

        app.dependency_overrides[fetch_user_from_rw_api] = _dep

    yield _set

    if original is not None:
        app.dependency_overrides[fetch_user_from_rw_api] = original
    else:
        app.dependency_overrides.pop(fetch_user_from_rw_api, None)


async def _seed_trace(trace_id: str, **kw) -> None:
    async with async_session_maker() as session:
        session.add(LangfuseTraceOrm(id=trace_id, parser_version=1, **kw))
        await session.commit()


async def _turn_fields(trace_id: str) -> tuple:
    """Read (turn_index, is_final_turn_in_thread) straight from the DB."""
    async with async_session_maker() as session:
        row = (
            await session.execute(
                select(LangfuseTraceOrm).where(LangfuseTraceOrm.id == trace_id)
            )
        ).scalar_one()
        return row.turn_index, row.is_final_turn_in_thread


def _stub_langfuse_fetch(monkeypatch, trace):
    """Stub the on-demand single-trace Langfuse fetch the detail endpoint uses."""

    class _Stub:
        @classmethod
        def from_env(cls):
            return cls()

        def fetch_trace(self, trace_id):
            return trace

    monkeypatch.setattr("src.api.routers.traces.LangfuseClient", _Stub)


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


@pytest.mark.asyncio
async def test_machine_key_with_scope_allowed(client, machine_auth_override):
    machine_auth_override([TRACES_READ])
    assert (await client.get("/api/traces", headers=H)).status_code == 200


@pytest.mark.asyncio
async def test_machine_key_without_scope_forbidden(
    client, machine_auth_override
):
    machine_auth_override([])
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


@pytest.mark.asyncio
async def test_list_surfaces_derived_fields(
    client, auth_override, superuser_factory
):
    """datasets_analysed/language/language_confidence are lifted from the
    ``derived`` JSONB onto each list item (so tracey's analytics can build its
    dataframe in one paginated fetch)."""
    su = await superuser_factory("su_derived@example.com")
    auth_override(su.id)
    await _seed_trace(
        "dv1",
        prompt="deforestation in Brazil",
        trace_timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
        derived={
            "datasets_analysed_cumulative": ["tree_cover_loss", "land_cover"],
            "language": "en",
            "language_confidence": 0.97,
        },
    )
    # a trace with no derived payload still serializes (fields default to None)
    await _seed_trace(
        "dv2",
        prompt="no derived here",
        trace_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )

    body = (await client.get("/api/traces", headers=H)).json()
    item = next(i for i in body["items"] if i["id"] == "dv1")
    assert item["datasets_analysed"] == ["tree_cover_loss", "land_cover"]
    assert item["language"] == "en"
    assert item["language_confidence"] == 0.97
    # derived itself is never leaked on the list item
    assert "derived" not in item

    empty = next(i for i in body["items"] if i["id"] == "dv2")
    assert empty["datasets_analysed"] is None
    assert empty["language"] is None


# --- detail ----------------------------------------------------------------
@pytest.mark.asyncio
async def test_detail_returns_derived_from_db_and_io_from_langfuse(
    client, auth_override, superuser_factory, monkeypatch
):
    su = await superuser_factory("su_detail@example.com")
    auth_override(su.id)
    await _seed_trace(
        "d1", outcome="ANSWER", answer="the answer", derived={"aoi_count": 1}
    )
    # input/output come live from Langfuse, not our DB
    _stub_langfuse_fetch(
        monkeypatch,
        {
            "input": {"messages": [{"type": "human", "content": "hi"}]},
            "output": {"messages": [], "aoi_selection": {"name": "Brazil"}},
        },
    )
    b = (await client.get("/api/traces/d1", headers=H)).json()
    assert b["answer"] == "the answer"  # from our DB
    assert b["derived"]["aoi_count"] == 1  # from our DB
    assert b["raw_available"] is True
    assert b["output"]["aoi_selection"]["name"] == "Brazil"  # from Langfuse
    assert b["input"]["messages"][0]["content"] == "hi"  # from Langfuse


@pytest.mark.asyncio
async def test_detail_raw_unavailable(
    client, auth_override, superuser_factory, monkeypatch
):
    su = await superuser_factory("su_unavail@example.com")
    auth_override(su.id)
    await _seed_trace("d2", outcome="ANSWER", answer="kept")
    _stub_langfuse_fetch(monkeypatch, None)  # Langfuse 404 / unreachable
    b = (await client.get("/api/traces/d2", headers=H)).json()
    assert b["raw_available"] is False
    assert b["input"] is None and b["output"] is None
    assert b["answer"] == "kept"  # derived columns still served


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


# --- turn position (Phase 0) -----------------------------------------------
@pytest.mark.asyncio
async def test_turn_index_surfaced_and_filtered(
    client, auth_override, superuser_factory
):
    su = await superuser_factory("su_turn@example.com")
    auth_override(su.id)
    for ti in (1, 2, 3):
        await _seed_trace(
            f"ti{ti}",
            session_id="ts",
            turn_index=ti,
            trace_timestamp=datetime(2026, 6, 1, ti, tzinfo=timezone.utc),
        )

    # turn_index is on the list item
    body = (await client.get("/api/traces?session_id=ts", headers=H)).json()
    assert {i["id"]: i["turn_index"] for i in body["items"]} == {
        "ti1": 1,
        "ti2": 2,
        "ti3": 3,
    }

    ft = (
        await client.get("/api/traces?first_turn_only=true", headers=H)
    ).json()
    assert [i["id"] for i in ft["items"]] == ["ti1"]

    ex = (await client.get("/api/traces?turn_index=2", headers=H)).json()
    assert [i["id"] for i in ex["items"]] == ["ti2"]

    mn = (await client.get("/api/traces?min_turn_index=2", headers=H)).json()
    assert sorted(i["id"] for i in mn["items"]) == ["ti2", "ti3"]

    mx = (await client.get("/api/traces?max_turn_index=1", headers=H)).json()
    assert [i["id"] for i in mx["items"]] == ["ti1"]


@pytest.mark.asyncio
async def test_turn_index_is_true_position_under_date_filter(
    client, auth_override, superuser_factory
):
    """A stored turn_index is the true in-session position, so a date filter that
    cuts a session mid-thread does NOT renumber the surviving turns (the client-
    side-reconstruction bug this replaces)."""
    su = await superuser_factory("su_turn_date@example.com")
    auth_override(su.id)
    for ti, day in ((1, 1), (2, 2), (3, 3)):
        await _seed_trace(
            f"d{ti}",
            session_id="ds",
            turn_index=ti,
            trace_timestamp=datetime(2026, 6, day, tzinfo=timezone.utc),
        )

    body = (
        await client.get("/api/traces?start=2026-06-02T00:00:00Z", headers=H)
    ).json()
    # earliest turn excluded, but survivors keep their true ordinals (2, 3)
    assert {i["id"]: i["turn_index"] for i in body["items"]} == {
        "d2": 2,
        "d3": 3,
    }
    # first_turn_only over that same window returns nothing (turn 1 is filtered
    # out) — not a renumbered "first of the filtered set".
    ft = (
        await client.get(
            "/api/traces?start=2026-06-02T00:00:00Z&first_turn_only=true",
            headers=H,
        )
    ).json()
    assert ft["items"] == []


@pytest.mark.asyncio
async def test_recompute_turn_positions_orders_flags_and_is_idempotent():
    # three turns of one session, seeded out of order, all turn_index NULL
    await _seed_trace(
        "r3",
        session_id="rs",
        trace_timestamp=datetime(2026, 6, 1, 3, tzinfo=timezone.utc),
    )
    await _seed_trace(
        "r1",
        session_id="rs",
        trace_timestamp=datetime(2026, 6, 1, 1, tzinfo=timezone.utc),
    )
    await _seed_trace(
        "r2",
        session_id="rs",
        trace_timestamp=datetime(2026, 6, 1, 2, tzinfo=timezone.utc),
    )

    async def _recompute():
        async with async_session_maker() as session:
            await recompute_turn_positions(session, {"rs"})
            await session.commit()

    await _recompute()
    assert await _turn_fields("r1") == (1, False)
    assert await _turn_fields("r2") == (2, False)
    assert await _turn_fields("r3") == (3, True)

    # idempotent: recomputing the same session yields identical ordinals
    await _recompute()
    assert await _turn_fields("r3") == (3, True)

    # a late/out-of-order trace shifts the final flag and extends the numbering
    await _seed_trace(
        "r4",
        session_id="rs",
        trace_timestamp=datetime(2026, 6, 1, 4, tzinfo=timezone.utc),
    )
    await _recompute()
    assert await _turn_fields("r3") == (3, False)
    assert await _turn_fields("r4") == (4, True)


# --- per-turn diffs (Phase 1) ----------------------------------------------
async def _diff_fields(trace_id: str) -> tuple:
    """Read (insight_created_this_turn, datasets_analysed_this_turn) from the DB."""
    async with async_session_maker() as session:
        row = (
            await session.execute(
                select(LangfuseTraceOrm).where(LangfuseTraceOrm.id == trace_id)
            )
        ).scalar_one()
        return row.insight_created_this_turn, row.datasets_analysed_this_turn


@pytest.mark.asyncio
async def test_recompute_computes_per_turn_diffs():
    """insight_created_this_turn is true only on the turn insight_id newly becomes
    non-null / changes; datasets_analysed_this_turn is the per-turn delta of the
    cumulative list, not the cumulative list itself."""
    # (id, hour, insight_id, cumulative datasets as of this turn)
    seeds = [
        ("p1", 1, None, ["a"]),
        ("p2", 2, "ins1", ["a", "b"]),
        ("p3", 3, "ins1", ["a", "b"]),
        ("p4", 4, "ins2", ["a", "b", "c"]),
    ]
    for tid, hour, ins, ds in seeds:
        await _seed_trace(
            tid,
            session_id="ps",
            insight_id=ins,
            derived={"datasets_analysed_cumulative": ds},
            trace_timestamp=datetime(2026, 6, 1, hour, tzinfo=timezone.utc),
        )

    async with async_session_maker() as session:
        await recompute_turn_positions(session, {"ps"})
        await session.commit()

    assert await _diff_fields("p1") == (False, ["a"])  # first turn: all new
    assert await _diff_fields("p2") == (True, ["b"])  # insight appears; +b
    assert await _diff_fields("p3") == (False, [])  # unchanged: nothing new
    assert await _diff_fields("p4") == (True, ["c"])  # insight changes; +c


@pytest.mark.asyncio
async def test_per_turn_diffs_surfaced_on_list_item(
    client, auth_override, superuser_factory
):
    su = await superuser_factory("su_diff@example.com")
    auth_override(su.id)
    await _seed_trace(
        "diff1",
        session_id="dfs",
        turn_index=2,
        insight_created_this_turn=True,
        datasets_analysed_this_turn=["b"],
        derived={"datasets_analysed_cumulative": ["a", "b"]},
        trace_timestamp=datetime(2026, 6, 1, 2, tzinfo=timezone.utc),
    )
    body = (await client.get("/api/traces?session_id=dfs", headers=H)).json()
    item = body["items"][0]
    assert item["insight_created_this_turn"] is True
    assert item["datasets_analysed_this_turn"] == ["b"]
    # the cumulative field still reflects the whole thread as of this turn
    assert item["datasets_analysed"] == ["a", "b"]
