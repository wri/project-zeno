"""Superuser-only endpoints for exploring ingested Langfuse traces.

Read path over ``langfuse_traces`` (see src/api/services/langfuse for ingestion).
List/detail here; analytics + conversation views live alongside. All derived
fields are turn-level (per the parser); cumulative thread state lives under
``derived`` and the analytics surface dedups per session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import require_superuser
from src.api.data_models import LangfuseTraceOrm
from src.api.schemas import UserModel
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
    turn_tokens: Optional[int] = None
    turn_tool_calls: Optional[int] = None
    tool_error_count: Optional[int] = None
    latency_seconds: Optional[float] = None
    total_cost: Optional[float] = None


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
    metadata: Optional[dict[str, Any]] = None
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
    LangfuseTraceOrm.turn_tokens,
    LangfuseTraceOrm.turn_tool_calls,
    LangfuseTraceOrm.tool_error_count,
    LangfuseTraceOrm.latency_seconds,
    LangfuseTraceOrm.total_cost,
)


def _filters(
    environment: Optional[str],
    outcome: Optional[str],
    user_id: Optional[str],
    session_id: Optional[str],
    start: Optional[datetime],
    end: Optional[datetime],
    prompt_contains: Optional[str],
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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _superuser: UserModel = Depends(require_superuser),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> TraceListResponse:
    """List/filter traces (derived columns only — never raw/output)."""
    conds = _filters(
        environment, outcome, user_id, session_id, start, end, prompt_contains
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
        items=[TraceListItem(**dict(r)) for r in rows],
    )


@router.get("/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: str,
    _superuser: UserModel = Depends(require_superuser),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> TraceDetail:
    """Full detail for one trace, including input/output (the AgentState
    snapshot) and the derived bundle."""
    row = (
        await session.execute(
            select(LangfuseTraceOrm).where(LangfuseTraceOrm.id == trace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    raw = row.raw if isinstance(row.raw, dict) else {}
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
        insight_id=row.insight_id,
        turn_tokens=row.turn_tokens,
        turn_input_tokens=row.turn_input_tokens,
        turn_output_tokens=row.turn_output_tokens,
        turn_tool_calls=row.turn_tool_calls,
        tool_error_count=row.tool_error_count,
        latency_seconds=row.latency_seconds,
        total_cost=row.total_cost,
        parser_version=row.parser_version,
        parse_error=row.parse_error,
        recognized_contract=row.recognized_contract,
        derived=row.derived,
        metadata=row.trace_metadata,
        input=raw.get("input"),
        output=raw.get("output"),
    )
