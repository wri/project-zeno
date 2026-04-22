"""Daily quota checking and enforcement."""

from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import APISettings
from src.api.data_models import DailyUsageOrm, UserType
from src.api.schemas import UserModel
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


async def get_user_identity_and_daily_quota(
    user: UserModel,
) -> dict:
    """
    Determine the user's identity string and their daily prompt quota.
    """
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
    user: UserModel,
    session: AsyncSession,
) -> dict:
    """
    Check the current daily usage quota for a user without incrementing.
    Returns empty dict if quota checking is disabled.
    """
    if not APISettings.enable_quota_checking:
        return {}

    identity_and_quota = await get_user_identity_and_daily_quota(user)

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
    user: UserModel,
    session: AsyncSession,
) -> dict:
    """
    Enforce daily usage quota, incrementing the count. Raises 429 if exceeded.
    Returns empty dict if quota checking is disabled.
    """
    if not APISettings.enable_quota_checking:
        return {}

    identity_and_quota = await get_user_identity_and_daily_quota(user)

    today = date.today()

    stmt = (
        insert(DailyUsageOrm)
        .values(
            id=identity_and_quota["identity"],
            date=today,
            usage_count=1,
            ip_address=None,
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
    return identity_and_quota
