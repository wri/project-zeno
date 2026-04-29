"""User profile and authentication endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import require_auth
from src.api.config import APISettings
from src.api.data_models import UserOrm
from src.api.schemas import (
    ProfileConfigResponse,
    UserModel,
    UserProfileUpdateRequest,
    UserWithQuotaModel,
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

    await session.commit()
    await session.refresh(db_user)

    return UserModel(
        id=db_user.id,
        name=db_user.name,
        email=db_user.email,
        created_at=db_user.created_at,
        updated_at=db_user.updated_at,
        user_type=db_user.user_type,
        threads=[],
        first_name=db_user.first_name,
        last_name=db_user.last_name,
        profile_description=db_user.profile_description,
        sector_code=db_user.sector_code,
        role_code=db_user.role_code,
        job_title=db_user.job_title,
        company_organization=db_user.company_organization,
        country_code=db_user.country_code,
        preferred_language_code=db_user.preferred_language_code,
        gis_expertise_level=db_user.gis_expertise_level,
        areas_of_interest=db_user.areas_of_interest,
        topics=json.loads(db_user.topics) if db_user.topics else None,
        receive_news_emails=db_user.receive_news_emails,
        help_test_features=db_user.help_test_features,
        has_profile=db_user.has_profile,
    )


@router.get("/api/profile/config", response_model=ProfileConfigResponse)
async def get_profile_config():
    """
    Get configuration options for profile dropdowns.

    Public endpoint (no auth required). Returns all valid values for
    sector, role, country, language, GIS expertise level, and topic fields.
    """
    return ProfileConfigResponse()
