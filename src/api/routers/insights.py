"""Insight retrieval and management endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.auth.dependencies import optional_auth, require_auth
from src.api.data_models import InsightOrm, UserType
from src.api.schemas import (
    InsightChartResponse,
    InsightPublicToggleRequest,
    InsightResponse,
    UserModel,
)
from src.shared.database import get_session_from_pool_dependency
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _row_to_response(row: InsightOrm) -> InsightResponse:
    return InsightResponse(
        id=row.id,
        user_id=row.user_id,
        thread_id=row.thread_id,
        insight_text=row.insight_text,
        follow_up_suggestions=row.follow_up_suggestions or [],
        charts=[
            InsightChartResponse(
                id=chart.id,
                position=chart.position,
                title=chart.title,
                chart_type=chart.chart_type,
                x_axis=chart.x_axis,
                y_axis=chart.y_axis,
                color_field=chart.color_field,
                stack_field=chart.stack_field,
                group_field=chart.group_field,
                series_fields=chart.series_fields or [],
                chart_data=chart.chart_data or [],
            )
            for chart in (row.charts or [])
        ],
        codeact_parts=[
            {"type": t, "content": c}
            for t, c in zip(
                row.codeact_types or [], row.codeact_contents or []
            )
        ],
        is_public=row.is_public,
        created_at=row.created_at,
    )


@router.get("/api/insights", response_model=list[InsightResponse])
async def list_insights(
    thread_id: Optional[str] = None,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """List all insights belonging to the authenticated user, optionally filtered by thread."""
    stmt = (
        select(InsightOrm)
        .options(selectinload(InsightOrm.charts))
        .where(InsightOrm.user_id == user.id)
    )
    if thread_id:
        stmt = stmt.where(InsightOrm.thread_id == thread_id)
    stmt = stmt.order_by(InsightOrm.created_at.desc())

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_row_to_response(row) for row in rows]


@router.get("/api/insights/{insight_id}", response_model=InsightResponse)
async def get_insight(
    insight_id: UUID,
    user: Optional[UserModel] = Depends(optional_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get a single insight. Public insights can be accessed by anyone.
    Private insights require authentication and ownership.
    """
    result = await session.execute(
        select(InsightOrm)
        .options(selectinload(InsightOrm.charts))
        .where(InsightOrm.id == insight_id)
    )
    row = result.scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Insight not found")

    if row.is_public:
        return _row_to_response(row)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if row.user_id != user.id and user.user_type != UserType.ADMIN:
        raise HTTPException(status_code=404, detail="Insight not found")

    return _row_to_response(row)


@router.patch(
    "/api/insights/{insight_id}/public",
    response_model=InsightResponse,
)
async def toggle_insight_public(
    insight_id: UUID,
    body: InsightPublicToggleRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Set or unset the is_public flag on an insight owned by the authenticated user."""
    result = await session.execute(
        select(InsightOrm)
        .options(selectinload(InsightOrm.charts))
        .where(InsightOrm.id == insight_id)
    )
    row = result.scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Insight not found")

    if row.user_id != user.id and user.user_type != UserType.ADMIN:
        raise HTTPException(status_code=404, detail="Insight not found")

    row.is_public = body.is_public
    await session.commit()
    await session.refresh(row)
    return _row_to_response(row)
