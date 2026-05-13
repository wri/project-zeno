"""Superuser-only admin endpoints (manage other users)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import _orm_to_user_model, require_superuser
from src.api.data_models import UserOrm, UserType
from src.api.schemas import UserModel, UserTypeUpdateRequest
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


@router.patch(
    "/api/admin/users/{user_id}/user-type", response_model=UserModel
)
async def update_user_type(
    user_id: str,
    body: UserTypeUpdateRequest,
    superuser: UserModel = Depends(require_superuser),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Set a user's user_type. Superuser-only."""
    result = await session.execute(
        select(UserOrm).where(UserOrm.id == user_id)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if (
        target.id == superuser.id
        and body.user_type != UserType.SUPERUSER
    ):
        raise HTTPException(
            status_code=400,
            detail="Superusers cannot demote themselves",
        )

    target.user_type = body.user_type.value
    target.updated_at = datetime.now()

    await session.commit()
    await session.refresh(target)

    return _orm_to_user_model(target)
