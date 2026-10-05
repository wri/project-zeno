"""User profile and authentication endpoints."""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import (
    _orm_to_user_model,
    require_auth,
    rw_bearer_token,
)
from src.api.config import APISettings
from src.api.data_models import UserOrm
from src.api.schemas import (
    ProfileConfigResponse,
    ProfilePrefillResponse,
    UserModel,
    UserProfileUpdateRequest,
    UserWithQuotaModel,
)
from src.api.services.profile_prefill import (
    ResourceWatchUnavailableError,
    get_profile_prefill,
)
from src.api.services.quota import check_quota
from src.shared.database import get_session_from_pool_dependency

router = APIRouter()


@router.get("/api/auth/me", response_model=UserWithQuotaModel)
async def auth_me(
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get current user information with quota usage.

    Requires Authorization: Bearer <JWT>.
    Returns full user profile including quota information.
    """
    if not APISettings.enable_quota_checking:
        return {
            **user.model_dump(),
            "prompts_used": None,
            "prompt_quota": None,
        }

    quota_info = await check_quota(user, session)
    return {**user.model_dump(), **quota_info}


@router.patch("/api/auth/profile", response_model=UserModel)
async def update_user_profile(
    profile_update: UserProfileUpdateRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Update user profile fields (partial update).

    Only provided fields will be updated. Dropdown fields are validated
    against configuration values from GET /api/profile/config.
    """
    result = await session.execute(
        select(UserOrm).where(UserOrm.id == user.id)
    )
    db_user = result.scalar_one_or_none()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = profile_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "topics" and value is not None:
            value = json.dumps(value)
        setattr(db_user, field, value)

    if "terms_version" in update_data:
        # Each acceptance is an event; only the server clock sets the time.
        db_user.terms_accepted_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(db_user)

    return _orm_to_user_model(db_user)


@router.get("/api/auth/profile/prefill", response_model=ProfilePrefillResponse)
async def get_profile_prefill_suggestion(
    user: UserModel = Depends(require_auth),
    rw_token: Optional[str] = Depends(rw_bearer_token),
):
    """
    Suggest profile fields from the caller's MyGFW profile.

    Read-only: nothing is written. The suggestion uses the
    PATCH /api/auth/profile field names and holds only fields that mapped
    to valid GNW values. Returns found=false when there is no MyGFW
    profile or nothing maps, and 502 when Resource Watch fails.
    """
    try:
        return await get_profile_prefill(user.id, rw_token)
    except ResourceWatchUnavailableError as e:
        raise HTTPException(
            status_code=502, detail="Error contacting Resource Watch"
        ) from e


@router.get("/api/profile/config", response_model=ProfileConfigResponse)
async def get_profile_config():
    """
    Get configuration options for profile dropdowns.

    Public endpoint (no auth required). Returns all valid values for
    sector, role, country, language, GIS expertise level, and topic fields.
    """
    return ProfileConfigResponse()
