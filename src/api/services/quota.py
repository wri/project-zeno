"""Daily quota checking and enforcement."""

from datetime import date
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import APISettings
from src.api.data_models import DailyUsageOrm, UserType
from src.api.schemas import UserModel
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

NEXTJS_IP_HEADER = "X-ZENO-FORWARDED-FOR"
ANONYMOUS_USER_PREFIX = "noauth"


async def extract_anonymous_session_cookie(request: Request) -> Optional[str]:
    """
    Extract the anonymous session cookie from the request headers.
    """
    auth_header = request.headers["Authorization"]
    credentials = auth_header.strip("Bearer ")
    [scheme, anonymous_id] = credentials.split(":", 1)
    return f"{ANONYMOUS_USER_PREFIX}:{anonymous_id}"


async def get_user_identity_and_daily_quota(
    request: Request,
    user: Optional[UserModel],
) -> dict:
    """
    Determine the user's identity string and their daily prompt quota.
    """
    if not user:
        daily_quota = APISettings.anonymous_user_daily_quota
        identity = await extract_anonymous_session_cookie(request)
    else:
        if user.user_type == UserType.ADMIN:
            daily_quota = APISettings.admin_user_daily_quota
        elif user.user_type == UserType.MACHINE:
            daily_quota = APISettings.machine_user_daily_quota
        elif user.user_type == UserType.PRO:
            daily_quota = APISettings.pro_user_daily_quota
        else:
            daily_quota = APISettings.regular_user_daily_quota
        identity = f"user:{user.id}"

    return {"identity": identity, "prompt_quota": daily_quota}


async def check_quota(
    request: Request,
    user: Optional[UserModel],
    session: AsyncSession,
) -> dict:
    """
    Check the current daily usage quota for a user without incrementing.
    Returns empty dict if quota checking is disabled.
    """
    if not APISettings.enable_quota_checking:
        return {}

    identity_and_quota = await get_user_identity_and_daily_quota(request, user)

    today = date.today()
    stmt = select(DailyUsageOrm).filter_by(
        id=identity_and_quota["identity"], date=today
    )
    result = await session.execute(stmt)
    daily_usage = result.scalars().first()

    identity_and_quota["prompts_used"] = (
        daily_usage.usage_count if daily_usage else 0
    )
    return identity_and_quota


async def enforce_quota(
    request: Request,
    user: Optional[UserModel],
    session: AsyncSession,
) -> dict:
    """
    Enforce daily usage quota, incrementing the count. Raises 429 if exceeded.
    Returns empty dict if quota checking is disabled.
    """
    if not APISettings.enable_quota_checking:
        return {}

    identity_and_quota = await get_user_identity_and_daily_quota(request, user)

    anonymous_user_ip = None
    user_is_anonymous = (
        identity_and_quota["identity"].split(":")[0] == ANONYMOUS_USER_PREFIX
    )
    if user_is_anonymous:
        anonymous_user_ip = request.headers.get(NEXTJS_IP_HEADER)

    today = date.today()

    stmt = (
        insert(DailyUsageOrm)
        .values(
            id=identity_and_quota["identity"],
            date=today,
            usage_count=1,
            ip_address=anonymous_user_ip,
        )
        .on_conflict_do_update(
            index_elements=["id", "date"],
            set_={"usage_count": DailyUsageOrm.usage_count + 1},
        )
        .returning(DailyUsageOrm.usage_count)
    )
    result = await session.execute(stmt)
    count = result.scalars().first()
    await session.commit()

    if count > identity_and_quota["prompt_quota"]:
        raise HTTPException(
            status_code=429,
            detail=f"Daily free limit of {identity_and_quota['prompt_quota']} exceeded; please try again tomorrow.",
        )

    identity_and_quota["prompts_used"] = count

    if user_is_anonymous:
        stmt = select(func.sum(DailyUsageOrm.usage_count)).filter_by(
            date=today, ip_address=anonymous_user_ip
        )
        result = await session.execute(stmt)
        ip_count = result.scalar() or 0

        if ip_count > APISettings.ip_address_daily_quota:
            raise HTTPException(
                status_code=429,
                detail=f"Daily free limit of {APISettings.ip_address_daily_quota} exceeded for IP address",
            )

    return identity_and_quota
