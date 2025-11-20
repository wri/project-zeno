from datetime import datetime

import bcrypt
import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    # Find active key by prefix
    stmt = (
        select(MachineUserKeyOrm, UserOrm)
        .join(UserOrm)
        .options(selectinload(UserOrm.threads))
        .where(
            MachineUserKeyOrm.key_prefix == key_prefix,
            MachineUserKeyOrm.is_active == True,  # noqa: E712
            UserOrm.user_type == UserType.MACHINE.value,
        )
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

    # Update last_used_at timestamp
    key_record.last_used_at = datetime.now()
    await session.commit()

    logger.info(
        "Machine user authenticated",
        user_id=user_record.id,
        key_name=key_record.key_name,
        key_prefix=key_prefix,
    )

    # Ensure machine user has a full profile to pass validation.
    # this is useful for local development with profiles that are
    # not complete.
    # user_record.topics = json.loads(user_record.topics) if user_record.topics else None
    # user_record.topics = []#json.loads(user_record.topics) if user_record.topics else None,
    # print("=="*50, user_record.topics)
    # print()
    # user_record.receive_news_emails = user_record.receive_news_emails or False
    # user_record.help_test_features = user_record.help_test_features or False
    # user_record.has_profile = True
    # user_record.threads = []
    # user_record.topics = []

    # user_dict = {
    #     "id": user_record.id,
    #     "name": user_record.name,
    #     "email": user_record.email,
    #     "created_at": user_record.created_at,
    #     "updated_at": user_record.updated_at,
    #     "user_type": user_record.user_type,
    #     "threads": [],
    #     "first_name": user_record.first_name,
    #     "last_name": user_record.last_name,
    #     "profile_description": user_record.profile_description,
    #     "sector_code": user_record.sector_code,
    #     "role_code": user_record.role_code,
    #     "job_title": user_record.job_title,
    #     "company_organization": user_record.company_organization,
    #     "country_code": user_record.country_code,
    #     "preferred_language_code": user_record.preferred_language_code,
    #     "gis_expertise_level": user_record.gis_expertise_level,
    #     "areas_of_interest": user_record.areas_of_interest,
    #     "topics": json.loads(user_record.topics) if user_record.topics else None,
    #     "receive_news_emails": user_record.receive_news_emails or False,
    #     "help_test_features": user_record.help_test_features or False,
    #     "has_profile": True,
    # }
    # return UserModel.model_validate(user_dict)
    return UserModel.model_validate(user_record)
