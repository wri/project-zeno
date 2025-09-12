from datetime import datetime

import bcrypt
import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.data_models import MachineUserKeyOrm, UserOrm, UserType
from src.api.schemas import UserModel

logger = structlog.get_logger()

MACHINE_USER_PREFIX = "zeno-key"


async def validate_machine_user_token(
    token: str, session: AsyncSession
) -> UserModel:
    """Validate machine user API key and return associated user."""
    # Parse token format: zeno-key:prefix:secret
    parts = token.split(":")
    if len(parts) != 3 or parts[0] != MACHINE_USER_PREFIX:
        raise HTTPException(
            status_code=401, detail="Invalid machine user token format"
        )

    key_prefix = parts[1]
    secret = parts[2]

    # Find active key by prefix with optimized query
    stmt = (
        select(MachineUserKeyOrm, UserOrm)
        .join(UserOrm)
        .where(
            MachineUserKeyOrm.key_prefix == key_prefix,
            MachineUserKeyOrm.is_active == True,  # noqa: E712
            UserOrm.user_type == UserType.MACHINE.value,
        )
        .limit(1)  # Add limit for better performance
    )

    result = await session.execute(stmt)
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=401, detail="Invalid or inactive machine user key"
        )

    key_record, user_record = row

    # Verify the secret matches the stored hash
    if not bcrypt.checkpw(
        secret.encode("utf-8"), key_record.key_hash.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid machine user key")

    # Check if key has expired
    if key_record.expires_at and key_record.expires_at < datetime.now():
        raise HTTPException(
            status_code=401, detail="Machine user key has expired"
        )

    # Update last_used_at timestamp asynchronously (don't block the request)
    # This reduces write contention under high load
    key_record.last_used_at = datetime.now()
    # Don't commit immediately - let the session close naturally
    # The update will be committed when the session context exits

    logger.info(
        "Machine user authenticated",
        user_id=user_record.id,
        key_name=key_record.key_name,
        key_prefix=key_prefix,
    )

    # Convert ORM to dict, avoiding lazy-loaded relationships, then add empty threads
    user_data = {
        c.name: getattr(user_record, c.name)
        for c in user_record.__table__.columns
    }
    user_data["threads"] = []  # Add empty threads for machine users
    return UserModel.model_validate(user_data)
