"""User whitelist and signup limit business logic."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import APISettings
from src.api.data_models import UserOrm, WhitelistedUserOrm


async def is_user_whitelisted(user_email: str, session: AsyncSession) -> bool:
    """
    Check if user is whitelisted via email or domain.
    Returns True if user is in email whitelist or domain whitelist.
    """
    user_email_lower = user_email.lower()
    user_domain = user_email_lower.split("@")[-1]

    stmt = select(WhitelistedUserOrm).where(
        func.lower(WhitelistedUserOrm.email) == user_email_lower
    )
    result = await session.execute(stmt)
    if result.scalars().first():
        return True

    domains_allowlist = APISettings.domains_allowlist
    normalized_domains = [domain.lower() for domain in domains_allowlist]
    return user_domain in normalized_domains


async def is_public_signup_open(session: AsyncSession) -> bool:
    """
    Check if public signups are currently open.
    Returns True if public signups are enabled and under user limit.
    """
    if not APISettings.allow_public_signups:
        return False

    max_signups = APISettings.max_user_signups
    if max_signups < 0:
        return True

    stmt = select(func.count(UserOrm.id))
    result = await session.execute(stmt)
    current_user_count = result.scalar()

    return current_user_count < max_signups


async def check_signup_limit_allows_new_user(
    user_email: str, session: AsyncSession
) -> bool:
    """
    Check if signup limits allow a new user to be created.
    Only applies to non-whitelisted users when public signups are enabled.
    Returns True if user can sign up, False if blocked by limits.
    """
    if await is_user_whitelisted(user_email, session):
        return True

    return await is_public_signup_open(session)
