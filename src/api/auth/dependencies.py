"""FastAPI authentication dependencies."""

import json
from typing import Optional

import cachetools
import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.machine_user import (
    MACHINE_USER_PREFIX,
    validate_machine_user_token,
)
from src.api.config import APISettings
from src.api.data_models import UserOrm
from src.api.schemas import UserModel
from src.api.services.auth import check_signup_limit_allows_new_user
from src.shared.database import get_session_from_pool_dependency
from src.shared.logging_config import bind_request_logging_context, get_logger

logger = get_logger(__name__)

NEXTJS_API_KEY_HEADER = "X-API-KEY"
NEXTJS_IP_HEADER = "X-ZENO-FORWARDED-FOR"
ANONYMOUS_USER_PREFIX = "noauth"

security = HTTPBearer(auto_error=False)

# LRU cache for user info, keyed by token
_user_info_cache = cachetools.TTLCache(maxsize=1024, ttl=60 * 60 * 24)  # 1 day


async def fetch_user_from_rw_api(
    request: Request,
    authorization: Optional[str] = Depends(security),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> UserModel:
    if not authorization:
        return None

    token = authorization.credentials

    if token and token.startswith(f"{MACHINE_USER_PREFIX}:"):
        return await validate_machine_user_token(token, session)

    if token and token.startswith(f"{ANONYMOUS_USER_PREFIX}:"):
        if request.headers.get(NEXTJS_API_KEY_HEADER) is None or (
            request.headers[NEXTJS_API_KEY_HEADER]
            != APISettings.nextjs_api_key
        ):
            raise HTTPException(
                status_code=403,
                detail="Invalid API key from NextJS for anonymous user",
            )

        anonymous_user_ip = request.headers.get(NEXTJS_IP_HEADER)
        if anonymous_user_ip is None or anonymous_user_ip.strip() == "":
            raise HTTPException(
                status_code=403,
                detail=f"Missing {NEXTJS_IP_HEADER} header for anonymous user",
            )

        return None

    if token and ":" in token:
        [scheme, _] = token.split(":", 1)
        if scheme.lower() != ANONYMOUS_USER_PREFIX:
            raise HTTPException(
                status_code=401,
                detail=f"Unauthorized, anonymous users should use '{ANONYMOUS_USER_PREFIX}' scheme",
            )

    if token and token in _user_info_cache:
        return _user_info_cache[token]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.resourcewatch.org/auth/user/me",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=10,
            )
    except Exception as e:
        logger.exception(f"Error contacting Resource Watch: {e}")
        raise HTTPException(
            status_code=502, detail=f"Error contacting Resource Watch: {e}"
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    user_info = resp.json()

    if "name" not in user_info:
        logger.warning(
            "User info does not contain the 'name' field, using email account name as fallback",
            email=user_info.get("email", None),
        )
        user_info["name"] = user_info["email"].split("@")[0]

    user_email = user_info["email"]

    if (
        not await check_signup_limit_allows_new_user(user_email, session)
        and not APISettings.allow_public_signups
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not allowed to access this API",
        )

    user_model = UserModel.model_validate(user_info)
    _user_info_cache[token] = user_model
    return user_model


def _orm_to_user_model(user: UserOrm) -> UserModel:
    """Convert a UserOrm instance to a UserModel."""
    return UserModel(
        id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at,
        updated_at=user.updated_at,
        user_type=user.user_type,
        first_name=user.first_name,
        last_name=user.last_name,
        profile_description=user.profile_description,
        sector_code=user.sector_code,
        role_code=user.role_code,
        job_title=user.job_title,
        company_organization=user.company_organization,
        country_code=user.country_code,
        preferred_language_code=user.preferred_language_code,
        gis_expertise_level=user.gis_expertise_level,
        areas_of_interest=user.areas_of_interest,
        topics=json.loads(user.topics) if user.topics else None,
        receive_news_emails=user.receive_news_emails,
        help_test_features=user.help_test_features,
        has_profile=user.has_profile,
    )


async def _get_or_create_user(
    user_info: UserModel, session: AsyncSession
) -> UserOrm:
    """Fetch user from DB, creating them if they don't exist yet."""
    stmt = select(UserOrm).filter_by(id=user_info.id)
    result = await session.execute(stmt)
    user = result.scalars().first()

    if not user:
        if not await check_signup_limit_allows_new_user(
            user_info.email, session
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User signups are currently closed",
            )
        user = UserOrm(**user_info.model_dump())
        session.add(user)
        await session.commit()

    return user


async def require_auth(
    user_info: UserModel = Depends(fetch_user_from_rw_api),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> UserModel:
    """Requires authentication - raises 401 if not authenticated."""
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token in Authorization header",
        )

    user = await _get_or_create_user(user_info, session)
    bind_request_logging_context(user_id=user.id)
    return _orm_to_user_model(user)


async def optional_auth(
    user_info: UserModel = Depends(fetch_user_from_rw_api),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> Optional[UserModel]:
    """Optional authentication - returns None if not authenticated."""
    if not user_info:
        return None

    user = await _get_or_create_user(user_info, session)
    bind_request_logging_context(user_id=user.id)
    return _orm_to_user_model(user)


async def fetch_user(
    user_info: UserModel = Depends(fetch_user_from_rw_api),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Deprecated: Use require_auth() or optional_auth() instead."""
    return await optional_auth(user_info, session)
