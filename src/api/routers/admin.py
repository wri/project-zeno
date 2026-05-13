"""Superuser-only admin endpoints (manage other users)."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import _orm_to_user_model, require_superuser
from src.api.data_models import UserOrm
from src.api.schemas import UserModel
from src.shared.database import get_session_from_pool_dependency

router = APIRouter()


@router.get("/api/admin/users", response_model=list[UserModel])
async def list_users(
    email: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _superuser: UserModel = Depends(require_superuser),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    List users for superuser administration.

    Optional case-insensitive substring filter on email. Pagination via
    `limit` (default 50, max 200) and `offset` (default 0). Ordered by
    `created_at DESC, id ASC` for deterministic paging.
    """
    stmt = select(UserOrm)
    if email is not None:
        stmt = stmt.where(func.lower(UserOrm.email).contains(email.lower()))
    stmt = stmt.order_by(UserOrm.created_at.desc(), UserOrm.id.asc())
    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    users = result.scalars().all()
    return [_orm_to_user_model(u) for u in users]
