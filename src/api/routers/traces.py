"""Endpoints for exploring ingested Langfuse traces.

Gated on the ``traces:read`` scope: a superuser human or a machine key carrying
that scope (see ``require_scope``).

Read path over ``langfuse_traces`` (see src/api/services/langfuse for ingestion):
list/detail, per-turn and turn-bucketed analytics, and a session (thread) view.
Each row is one turn; most fields are per-turn, but a few (``datasets_analysed``,
``has_insight``, ``primary_dataset_name``) carry thread-cumulative state and are
labelled as such. Only ``/sessions`` groups by session.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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
    primary_dataset_name: Optional[str] = Field(
        None,
        description=(
            "Thread-cumulative as of this turn: the primary dataset in effect at "
            "this turn, which may have been selected on an earlier turn. For the "
            "datasets newly analysed on this turn use datasets_analysed_this_turn."
        ),
    )
    has_insight: Optional[bool] = Field(
        None,
        description=(
            "Thread-cumulative as of this turn: whether an insight exists in the "
            "thread as of this turn (possibly created earlier). For whether *this* "
            "turn created one use insight_created_this_turn."
        ),
    )
    is_global: Optional[bool] = None
    # 1-based position of this turn within its session (ordered by
    # trace_timestamp); session-less traces are singletons (turn_index 1).
    turn_index: Optional[int] = None
    # Per-turn diffs (honest "this turn" signals, vs. the cumulative fields above).
    insight_created_this_turn: Optional[bool] = Field(
        None,
        description="True only on the turn whose insight_id first became non-null.",
    )
    datasets_analysed_this_turn: Optional[list[str]] = Field(
        None,
        description=(
            "Datasets new to this turn (this turn's cumulative set minus the "
            "previous turn's), vs. datasets_analysed which is thread-cumulative."
        ),
    )
    turn_tokens: Optional[int] = None
    turn_tool_calls: Optional[int] = None
    tool_error_count: Optional[int] = None
    latency_seconds: Optional[float] = None
    total_cost: Optional[float] = None
    # Sourced from the ``derived`` JSONB (long-tail fields kept out of columns).
    datasets_analysed: Optional[list[str]] = Field(
        None,
        description=(
            "Thread-cumulative as of this turn: every dataset analysed in the "
            "thread up to and including this turn. For the per-turn delta use "
            "datasets_analysed_this_turn."
        ),
    )
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
    LangfuseTraceOrm.insight_created_this_turn,
    LangfuseTraceOrm.datasets_analysed_this_turn,
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


@dataclass
class TurnAnalyticsFilters:
    """Shared query-param filter set for the list + analytics endpoints. The
    turn-position filters compare the stored, indexed ``turn_index`` (so no window);
    ``first_turn_only`` is a convenience alias for ``turn_index == 1``."""

    environment: Annotated[Optional[str], Query()] = None
    outcome: Annotated[Optional[str], Query()] = None
    user_id: Annotated[Optional[str], Query()] = None
    start: Annotated[
        Optional[datetime], Query(description="trace_timestamp >= (ISO)")
    ] = None
    end: Annotated[
        Optional[datetime], Query(description="trace_timestamp < (ISO)")
    ] = None
    turn_index: Annotated[
        Optional[int],
        Query(ge=1, description="exact 1-based turn position in the session"),
    ] = None
    min_turn_index: Annotated[Optional[int], Query(ge=1)] = None
    max_turn_index: Annotated[Optional[int], Query(ge=1)] = None
    first_turn_only: Annotated[
        bool, Query(description="only first turns (alias for turn_index=1)")
    ] = False

    def __post_init__(self) -> None:
        _check_turn_range(self.min_turn_index, self.max_turn_index)


@dataclass
class ListFilters(TurnAnalyticsFilters):
    """TurnAnalyticsFilters plus the list-only text filters."""

    session_id: Annotated[Optional[str], Query()] = None
    prompt_contains: Annotated[Optional[str], Query()] = None


def _filters(flt: ListFilters) -> list[Any]:
    conds: list[Any] = []
    if flt.environment:
        conds.append(LangfuseTraceOrm.environment == flt.environment)
    if flt.outcome:
        conds.append(LangfuseTraceOrm.outcome == flt.outcome)
    if flt.user_id:
        conds.append(LangfuseTraceOrm.user_id == flt.user_id)
    if flt.session_id:
        conds.append(LangfuseTraceOrm.session_id == flt.session_id)
    if flt.start:
        conds.append(LangfuseTraceOrm.trace_timestamp >= flt.start)
    if flt.end:
        conds.append(LangfuseTraceOrm.trace_timestamp < flt.end)
    if flt.prompt_contains:
        conds.append(LangfuseTraceOrm.prompt.ilike(f"%{flt.prompt_contains}%"))
    if flt.first_turn_only:
        conds.append(LangfuseTraceOrm.turn_index == 1)
    if flt.turn_index is not None:
        conds.append(LangfuseTraceOrm.turn_index == flt.turn_index)
    if flt.min_turn_index is not None:
        conds.append(LangfuseTraceOrm.turn_index >= flt.min_turn_index)
    if flt.max_turn_index is not None:
        conds.append(LangfuseTraceOrm.turn_index <= flt.max_turn_index)
    return conds


@router.get("", response_model=TraceListResponse)
async def list_traces(
    flt: ListFilters = Depends(),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _reader: UserModel = Depends(require_scope(TRACES_READ)),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> TraceListResponse:
    """List/filter traces (derived columns only — never raw/output)."""
    conds = _filters(flt)

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


class TurnMetrics(BaseModel):
    """The scalar metric block shared by ``/analytics/by-turn``'s grand total and
    each per-turn bucket (same shape as the corresponding fields on
    ``TraceAnalytics``)."""

    total_traces: int
    latency: dict[str, Optional[float]]  # {avg, p50, p95}
    cost: dict[str, Optional[float]] = Field(
        ...,
        description=(
            "{avg, p95, total}. The sums (total) are within-bucket totals and are "
            "NOT comparable across buckets — the terminal bucket aggregates many "
            "turn positions. Compare averages/percentiles across buckets."
        ),
    )
    tokens: dict[str, Optional[float]]  # {avg_turn_tokens, total_turn_tokens}
    tool_usage: dict[str, Optional[float]]  # {avg_tool_calls, tool_error_rate}


class TurnGroup(TurnMetrics):
    """One turn-position bucket. Positions at/above ``turn_bucket_cap`` collapse
    into a single terminal bucket, so ``turn_index`` is the bucket label
    (``== cap`` means "cap or more") while ``turn_index_min``/``turn_index_max``
    give the true range within it."""

    turn_index: int
    is_terminal: bool = Field(
        ...,
        description=(
            "The collapsing bucket (turn_index == turn_bucket_cap). True here does "
            "NOT by itself mean turns beyond the cap exist — check turn_index_max > "
            "turn_bucket_cap for that."
        ),
    )
    turn_index_min: int
    turn_index_max: int
    sessions_reaching: int = Field(
        ...,
        description=(
            "Distinct sessions that reached this turn position (a funnel/retention "
            "curve). A session spans buckets, so this is NOT summable across buckets."
        ),
    )


class TurnAnalytics(BaseModel):
    turn_bucket_cap: int
    ungrouped_traces: int = Field(
        ...,
        description=(
            "Traces with a NULL turn_index (excluded from groups). "
            "sum(groups.total_traces) + ungrouped_traces == grand_total.total_traces."
        ),
    )
    grand_total: TurnMetrics
    groups: list[TurnGroup]


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
    flt: TurnAnalyticsFilters, *, require_session: bool = False
) -> tuple[str, dict[str, Any]]:
    """Build a parameterised WHERE clause (bound params — no injection). The
    turn-position filters compare the stored, indexed ``turn_index``, so the
    aggregate SQL stays window-free."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if require_session:
        clauses.append("session_id IS NOT NULL")
    if flt.environment:
        clauses.append("environment = :environment")
        params["environment"] = flt.environment
    if flt.outcome:
        clauses.append("outcome = :outcome")
        params["outcome"] = flt.outcome
    if flt.user_id:
        clauses.append("user_id = :user_id")
        params["user_id"] = flt.user_id
    if flt.start:
        clauses.append("trace_timestamp >= :start")
        params["start"] = flt.start
    if flt.end:
        clauses.append("trace_timestamp < :end")
        params["end"] = flt.end
    if flt.first_turn_only:
        clauses.append("turn_index = 1")
    if flt.turn_index is not None:
        clauses.append("turn_index = :turn_index")
        params["turn_index"] = flt.turn_index
    if flt.min_turn_index is not None:
        clauses.append("turn_index >= :min_turn_index")
        params["min_turn_index"] = flt.min_turn_index
    if flt.max_turn_index is not None:
        clauses.append("turn_index <= :max_turn_index")
        params["max_turn_index"] = flt.max_turn_index
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _f(x: Any) -> Optional[float]:
    return round(float(x), 4) if x is not None else None


def _check_turn_range(
    min_turn_index: Optional[int], max_turn_index: Optional[int]
) -> None:
    if (
        min_turn_index is not None
        and max_turn_index is not None
        and min_turn_index > max_turn_index
    ):
        raise HTTPException(
            status_code=422,
            detail="min_turn_index must be <= max_turn_index",
        )


# The scalar aggregate expressions shared by /analytics' summary and
# /analytics/by-turn's grand-total + grouped queries, so the two can't drift.
# Consumed via _metrics_from_row (reads the aliased columns below).
_SCALAR_METRICS_SQL = """
  count(*) AS total,
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
""".strip()


def _metrics_dict(r: Any) -> dict[str, Any]:
    """Map a result row carrying the _SCALAR_METRICS_SQL columns into the
    TurnMetrics field dict (splat into TurnMetrics or TurnGroup)."""
    return {
        "total_traces": int(r["total"] or 0),
        "latency": {
            "avg": _f(r["lat_avg"]),
            "p50": _f(r["lat_p50"]),
            "p95": _f(r["lat_p95"]),
        },
        "cost": {
            "avg": _f(r["cost_avg"]),
            "p95": _f(r["cost_p95"]),
            "total": _f(r["cost_total"]),
        },
        "tokens": {
            "avg_turn_tokens": _f(r["tok_avg"]),
            "total_turn_tokens": _f(r["tok_total"]),
        },
        "tool_usage": {
            "avg_tool_calls": _f(r["tool_avg"]),
            "tool_error_rate": _f(r["tool_err_rate"]),
        },
    }


@router.get("/analytics", response_model=TraceAnalytics)
async def trace_analytics(
    flt: TurnAnalyticsFilters = Depends(),
    _reader: UserModel = Depends(require_scope(TRACES_READ)),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> TraceAnalytics:
    """Server-side aggregates over the filtered trace set. All metrics are
    turn-level (one row per trace), so counts/sums are not double-counted. The
    turn-position filters answer "how does turn 1 differ from turn 3+" via two
    calls, filtering the indexed ``turn_index`` (no window)."""
    where, params = _where_sql(flt)

    summary = (
        (
            await session.execute(
                text(
                    f"SELECT {_SCALAR_METRICS_SQL}, "
                    f"count(DISTINCT session_id) AS sessions, "
                    f"count(DISTINCT user_id) AS users "
                    f"FROM langfuse_traces{where}"
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    metrics = _metrics_dict(summary)

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
        unique_sessions=int(summary["sessions"] or 0),
        unique_users=int(summary["users"] or 0),
        outcome_breakdown=[NamedCount(**dict(r)) for r in outcomes],
        daily_volume=[DailyCount(**dict(r)) for r in daily],
        aoi_type_breakdown=[NamedCount(**dict(r)) for r in aoi],
        **metrics,
    )


@router.get("/analytics/by-turn", response_model=TurnAnalytics)
async def trace_analytics_by_turn(
    flt: TurnAnalyticsFilters = Depends(),
    turn_bucket_cap: int = Query(
        10,
        ge=1,
        le=50,
        description="turn positions >= this collapse into one terminal bucket",
    ),
    _reader: UserModel = Depends(require_scope(TRACES_READ)),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> TurnAnalytics:
    """The same scalar metrics as ``/analytics`` but broken down per turn position,
    so "how do turns evolve within a session" is a single call. Positions at/above
    ``turn_bucket_cap`` collapse into one terminal bucket. Any turn-position filter
    applies *before* bucketing (filter, then bucket). Filters compose with the
    stored, indexed ``turn_index`` — no window, no view."""
    where, params = _where_sql(flt)

    # Grand total over the whole filtered set (includes NULL-turn rows), plus the
    # NULL-turn count so groups (which exclude NULLs) reconcile against it.
    grand = (
        (
            await session.execute(
                text(
                    f"SELECT {_SCALAR_METRICS_SQL}, "
                    f"count(*) FILTER (WHERE turn_index IS NULL) AS ungrouped "
                    f"FROM langfuse_traces{where}"
                ),
                params,
            )
        )
        .mappings()
        .one()
    )

    # Per-bucket: LEAST(turn_index, cap) folds the tail; min/max expose the true
    # range (so the terminal label is honest); sessions_reaching is the funnel.
    group_rows = (
        (
            await session.execute(
                text(
                    f"SELECT LEAST(turn_index, :cap) AS turn_index, "
                    f"min(turn_index) AS turn_index_min, "
                    f"max(turn_index) AS turn_index_max, "
                    f"count(DISTINCT session_id) AS sessions_reaching, "
                    f"{_SCALAR_METRICS_SQL} FROM langfuse_traces{where}"
                    f"{' AND' if where else ' WHERE'} turn_index IS NOT NULL "
                    f"GROUP BY 1 ORDER BY 1"
                ),
                {**params, "cap": turn_bucket_cap},
            )
        )
        .mappings()
        .all()
    )

    groups = [
        TurnGroup(
            turn_index=int(r["turn_index"]),
            is_terminal=int(r["turn_index"]) == turn_bucket_cap,
            turn_index_min=int(r["turn_index_min"]),
            turn_index_max=int(r["turn_index_max"]),
            sessions_reaching=int(r["sessions_reaching"] or 0),
            **_metrics_dict(r),
        )
        for r in group_rows
    ]

    return TurnAnalytics(
        turn_bucket_cap=turn_bucket_cap,
        ungrouped_traces=int(grand["ungrouped"] or 0),
        grand_total=TurnMetrics(**_metrics_dict(grand)),
        groups=groups,
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
        TurnAnalyticsFilters(
            environment=environment, user_id=user_id, start=start, end=end
        ),
        require_session=True,
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
        insight_created_this_turn=row.insight_created_this_turn,
        datasets_analysed_this_turn=row.datasets_analysed_this_turn,
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
