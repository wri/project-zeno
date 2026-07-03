"""Endpoints for exploring ingested Langfuse traces.

Gated on the ``traces:read`` scope: a superuser human or a machine key carrying
that scope (see ``require_scope``).

Read path over ``langfuse_traces`` (see src/api/services/langfuse for ingestion).
List/detail here; analytics + conversation views live alongside. All derived
fields are turn-level (per the parser); cumulative thread state lives under
``derived`` and the analytics surface dedups per session.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import require_scope
from src.api.auth.scopes import TRACES_READ
from src.api.data_models import LangfuseTraceOrm
from src.api.schemas import UserModel
from src.api.services.langfuse.fetch import LangfuseClient
from src.shared.database import get_session_from_pool_dependency

router = APIRouter(prefix="/api/traces", tags=["traces"])


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #
class TraceListItem(BaseModel):
    id: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    environment: Optional[str] = None
    trace_timestamp: Optional[datetime] = None
    outcome: Optional[str] = None
    prompt: Optional[str] = None
    aoi_name: Optional[str] = None
    aoi_type: Optional[str] = None
    primary_dataset_name: Optional[str] = None
    has_insight: Optional[bool] = None
    is_global: Optional[bool] = None
    # 1-based position of this turn within its session (ordered by
    # trace_timestamp); session-less traces are singletons (turn_index 1).
    turn_index: Optional[int] = None
    turn_tokens: Optional[int] = None
    turn_tool_calls: Optional[int] = None
    tool_error_count: Optional[int] = None
    latency_seconds: Optional[float] = None
    total_cost: Optional[float] = None
    # Sourced from the ``derived`` JSONB (long-tail fields kept out of columns).
    datasets_analysed: Optional[list[str]] = None
    language: Optional[str] = None
    language_confidence: Optional[float] = None


class TraceListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TraceListItem]


class TraceDetail(TraceListItem):
    answer: Optional[str] = None
    has_answer: Optional[bool] = None
    answer_finish_reason: Optional[str] = None
    answer_is_refusal: Optional[bool] = None
    had_tool_call: Optional[bool] = None
    insight_id: Optional[str] = None
    turn_input_tokens: Optional[int] = None
    turn_output_tokens: Optional[int] = None
    parser_version: Optional[int] = None
    parse_error: Optional[str] = None
    recognized_contract: Optional[bool] = None
    derived: Optional[dict[str, Any]] = None
    # input/output are fetched live from Langfuse (the raw-trace store of record);
    # raw_available is False if Langfuse 404s or is unreachable.
    raw_available: bool = False
    input: Optional[Any] = None
    output: Optional[Any] = None


_LIST_COLUMNS = (
    LangfuseTraceOrm.id,
    LangfuseTraceOrm.session_id,
    LangfuseTraceOrm.user_id,
    LangfuseTraceOrm.environment,
    LangfuseTraceOrm.trace_timestamp,
    LangfuseTraceOrm.outcome,
    LangfuseTraceOrm.prompt,
    LangfuseTraceOrm.aoi_name,
    LangfuseTraceOrm.aoi_type,
    LangfuseTraceOrm.primary_dataset_name,
    LangfuseTraceOrm.has_insight,
    LangfuseTraceOrm.is_global,
    LangfuseTraceOrm.turn_index,
    LangfuseTraceOrm.turn_tokens,
    LangfuseTraceOrm.turn_tool_calls,
    LangfuseTraceOrm.tool_error_count,
    LangfuseTraceOrm.latency_seconds,
    LangfuseTraceOrm.total_cost,
    # Selected so the list response can surface the derived fields below without
    # a per-trace detail fetch (datasets_analysed/language live in JSONB).
    LangfuseTraceOrm.derived,
)


def _list_item_from_row(r: dict[str, Any]) -> TraceListItem:
    """Build a list item from a row mapping, lifting the three derived fields
    out of the ``derived`` JSONB and dropping it from the column kwargs."""
    derived = r.get("derived") or {}
    cols = {k: v for k, v in r.items() if k != "derived"}
    return TraceListItem(
        **cols,
        datasets_analysed=derived.get("datasets_analysed_cumulative"),
        language=derived.get("language"),
        language_confidence=derived.get("language_confidence"),
    )


def _filters(
    environment: Optional[str],
    outcome: Optional[str],
    user_id: Optional[str],
    session_id: Optional[str],
    start: Optional[datetime],
    end: Optional[datetime],
    prompt_contains: Optional[str],
    turn_index: Optional[int] = None,
    min_turn_index: Optional[int] = None,
    max_turn_index: Optional[int] = None,
    first_turn_only: bool = False,
) -> list[Any]:
    conds: list[Any] = []
    if environment:
        conds.append(LangfuseTraceOrm.environment == environment)
    if outcome:
        conds.append(LangfuseTraceOrm.outcome == outcome)
    if user_id:
        conds.append(LangfuseTraceOrm.user_id == user_id)
    if session_id:
        conds.append(LangfuseTraceOrm.session_id == session_id)
    if start:
        conds.append(LangfuseTraceOrm.trace_timestamp >= start)
    if end:
        conds.append(LangfuseTraceOrm.trace_timestamp < end)
    if prompt_contains:
        conds.append(LangfuseTraceOrm.prompt.ilike(f"%{prompt_contains}%"))
    # Turn-position filters (stored turn_index -> true position, index-backed).
    # first_turn_only is a convenience alias for turn_index == 1.
    if first_turn_only:
        conds.append(LangfuseTraceOrm.turn_index == 1)
    if turn_index is not None:
        conds.append(LangfuseTraceOrm.turn_index == turn_index)
    if min_turn_index is not None:
        conds.append(LangfuseTraceOrm.turn_index >= min_turn_index)
    if max_turn_index is not None:
        conds.append(LangfuseTraceOrm.turn_index <= max_turn_index)
    return conds


@router.get("", response_model=TraceListResponse)
async def list_traces(
    environment: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    start: Optional[datetime] = Query(
        None, description="trace_timestamp >= (ISO)"
    ),
    end: Optional[datetime] = Query(
        None, description="trace_timestamp < (ISO)"
    ),
    prompt_contains: Optional[str] = Query(None),
    turn_index: Optional[int] = Query(
        None,
        ge=1,
        description="exact 1-based turn position within the session",
    ),
    min_turn_index: Optional[int] = Query(None, ge=1),
    max_turn_index: Optional[int] = Query(None, ge=1),
    first_turn_only: bool = Query(
        False, description="only first turns (alias for turn_index=1)"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _reader: UserModel = Depends(require_scope(TRACES_READ)),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> TraceListResponse:
    """List/filter traces (derived columns only — never raw/output)."""
    conds = _filters(
        environment,
        outcome,
        user_id,
        session_id,
        start,
        end,
        prompt_contains,
        turn_index,
        min_turn_index,
        max_turn_index,
        first_turn_only,
    )

    count_stmt = select(func.count()).select_from(LangfuseTraceOrm)
    for c in conds:
        count_stmt = count_stmt.where(c)
    total = int((await session.execute(count_stmt)).scalar() or 0)

    stmt = select(*_LIST_COLUMNS)
    for c in conds:
        stmt = stmt.where(c)
    stmt = stmt.order_by(LangfuseTraceOrm.trace_timestamp.desc().nullslast())
    stmt = stmt.limit(limit).offset(offset)
    rows = (await session.execute(stmt)).mappings().all()

    return TraceListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_list_item_from_row(dict(r)) for r in rows],
    )


# --------------------------------------------------------------------------- #
# Analytics + sessions (declared BEFORE /{trace_id} so literals aren't shadowed)
# --------------------------------------------------------------------------- #
class NamedCount(BaseModel):
    value: Optional[str] = None
    count: int


class DailyCount(BaseModel):
    day: date
    count: int


class TraceAnalytics(BaseModel):
    total_traces: int
    unique_sessions: int
    unique_users: int
    outcome_breakdown: list[NamedCount]
    daily_volume: list[DailyCount]
    aoi_type_breakdown: list[NamedCount]
    latency: dict[str, Optional[float]]
    cost: dict[str, Optional[float]]
    tokens: dict[str, Optional[float]]
    tool_usage: dict[str, Optional[float]]


class SessionItem(BaseModel):
    session_id: str
    user_id: Optional[str] = None
    environment: Optional[str] = None
    first_prompt: Optional[str] = None
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    turn_count: int


class SessionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SessionItem]


def _where_sql(
    environment: Optional[str],
    outcome: Optional[str],
    user_id: Optional[str],
    start: Optional[datetime],
    end: Optional[datetime],
    *,
    require_session: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Build a parameterised WHERE clause (bound params — no injection)."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if require_session:
        clauses.append("session_id IS NOT NULL")
    if environment:
        clauses.append("environment = :environment")
        params["environment"] = environment
    if outcome:
        clauses.append("outcome = :outcome")
        params["outcome"] = outcome
    if user_id:
        clauses.append("user_id = :user_id")
        params["user_id"] = user_id
    if start:
        clauses.append("trace_timestamp >= :start")
        params["start"] = start
    if end:
        clauses.append("trace_timestamp < :end")
        params["end"] = end
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _f(x: Any) -> Optional[float]:
    return round(float(x), 4) if x is not None else None


@router.get("/analytics", response_model=TraceAnalytics)
async def trace_analytics(
    environment: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    _reader: UserModel = Depends(require_scope(TRACES_READ)),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> TraceAnalytics:
    """Server-side aggregates over the filtered trace set. All metrics are
    turn-level (one row per trace), so counts/sums are not double-counted."""
    where, params = _where_sql(environment, outcome, user_id, start, end)

    summary = (
        (
            await session.execute(
                text(
                    f"""
                SELECT
                  count(*) AS total,
                  count(DISTINCT session_id) AS sessions,
                  count(DISTINCT user_id) AS users,
                  avg(latency_seconds) AS lat_avg,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_seconds) AS lat_p50,
                  percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_seconds) AS lat_p95,
                  avg(total_cost) AS cost_avg,
                  percentile_cont(0.95) WITHIN GROUP (ORDER BY total_cost) AS cost_p95,
                  sum(total_cost) AS cost_total,
                  avg(turn_tokens) AS tok_avg,
                  sum(turn_tokens) AS tok_total,
                  avg(turn_tool_calls) AS tool_avg,
                  avg(CASE WHEN tool_error_count > 0 THEN 1.0 ELSE 0.0 END) AS tool_err_rate
                FROM langfuse_traces{where}
                """
                ),
                params,
            )
        )
        .mappings()
        .one()
    )

    outcomes = (
        (
            await session.execute(
                text(
                    f"SELECT outcome AS value, count(*) AS count FROM langfuse_traces"
                    f"{where} GROUP BY outcome ORDER BY count DESC"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    daily = (
        (
            await session.execute(
                text(
                    f"SELECT date_trunc('day', trace_timestamp)::date AS day, "
                    f"count(*) AS count FROM langfuse_traces{where} "
                    f"GROUP BY day ORDER BY day"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    aoi = (
        (
            await session.execute(
                text(
                    f"SELECT aoi_type AS value, count(*) AS count FROM langfuse_traces"
                    f"{where}{' AND' if where else ' WHERE'} aoi_type IS NOT NULL "
                    f"GROUP BY aoi_type ORDER BY count DESC"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    return TraceAnalytics(
        total_traces=int(summary["total"] or 0),
        unique_sessions=int(summary["sessions"] or 0),
        unique_users=int(summary["users"] or 0),
        outcome_breakdown=[NamedCount(**dict(r)) for r in outcomes],
        daily_volume=[DailyCount(**dict(r)) for r in daily],
        aoi_type_breakdown=[NamedCount(**dict(r)) for r in aoi],
        latency={
            "avg": _f(summary["lat_avg"]),
            "p50": _f(summary["lat_p50"]),
            "p95": _f(summary["lat_p95"]),
        },
        cost={
            "avg": _f(summary["cost_avg"]),
            "p95": _f(summary["cost_p95"]),
            "total": _f(summary["cost_total"]),
        },
        tokens={
            "avg_turn_tokens": _f(summary["tok_avg"]),
            "total_turn_tokens": _f(summary["tok_total"]),
        },
        tool_usage={
            "avg_tool_calls": _f(summary["tool_avg"]),
            "tool_error_rate": _f(summary["tool_err_rate"]),
        },
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    environment: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _reader: UserModel = Depends(require_scope(TRACES_READ)),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> SessionListResponse:
    """Conversation browser: one row per session (thread), newest first, with the
    first prompt of the thread and a turn count."""
    where, params = _where_sql(
        environment, None, user_id, start, end, require_session=True
    )

    total = int(
        (
            await session.execute(
                text(
                    f"SELECT count(DISTINCT session_id) FROM langfuse_traces{where}"
                ),
                params,
            )
        ).scalar()
        or 0
    )

    rows = (
        (
            await session.execute(
                text(
                    f"""
                SELECT session_id,
                       max(user_id) AS user_id,
                       max(environment) AS environment,
                       (array_agg(prompt ORDER BY trace_timestamp ASC))[1] AS first_prompt,
                       min(trace_timestamp) AS first_timestamp,
                       max(trace_timestamp) AS last_timestamp,
                       count(*) AS turn_count
                FROM langfuse_traces{where}
                GROUP BY session_id
                ORDER BY max(trace_timestamp) DESC NULLS LAST
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )

    return SessionListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[SessionItem(**dict(r)) for r in rows],
    )


@router.get("/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: str,
    _reader: UserModel = Depends(require_scope(TRACES_READ)),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> TraceDetail:
    """Full detail for one trace: our derived columns from Postgres, plus the
    `input`/`output` (the AgentState snapshot) fetched live from Langfuse, which
    is the store of record for the raw trace."""
    row = (
        await session.execute(
            select(LangfuseTraceOrm).where(LangfuseTraceOrm.id == trace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    trace = await asyncio.to_thread(
        LangfuseClient.from_env().fetch_trace, trace_id
    )
    raw_available = isinstance(trace, dict)
    trace = trace or {}

    derived = row.derived or {}

    return TraceDetail(
        id=row.id,
        session_id=row.session_id,
        user_id=row.user_id,
        environment=row.environment,
        trace_timestamp=row.trace_timestamp,
        outcome=row.outcome,
        prompt=row.prompt,
        answer=row.answer,
        has_answer=row.has_answer,
        answer_finish_reason=row.answer_finish_reason,
        answer_is_refusal=row.answer_is_refusal,
        had_tool_call=row.had_tool_call,
        aoi_name=row.aoi_name,
        aoi_type=row.aoi_type,
        primary_dataset_name=row.primary_dataset_name,
        has_insight=row.has_insight,
        is_global=row.is_global,
        turn_index=row.turn_index,
        insight_id=row.insight_id,
        turn_tokens=row.turn_tokens,
        turn_input_tokens=row.turn_input_tokens,
        turn_output_tokens=row.turn_output_tokens,
        turn_tool_calls=row.turn_tool_calls,
        tool_error_count=row.tool_error_count,
        latency_seconds=row.latency_seconds,
        total_cost=row.total_cost,
        datasets_analysed=derived.get("datasets_analysed_cumulative"),
        language=derived.get("language"),
        language_confidence=derived.get("language_confidence"),
        parser_version=row.parser_version,
        parse_error=row.parse_error,
        recognized_contract=row.recognized_contract,
        derived=row.derived,
        raw_available=raw_available,
        input=trace.get("input"),
        output=trace.get("output"),
    )
