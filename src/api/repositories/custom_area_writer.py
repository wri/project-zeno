"""Rename and delete a user's custom area together with its ``aois`` mirror.

The caller controls the transaction, as with ``aoi_sync``: these functions
don't commit, so the caller commits and then notifies the analytics API.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.data_models import CustomAreaOrm
from src.api.services.aoi_sync import delete_custom_aoi, upsert_custom_aoi


async def get_owned_custom_area(
    session: AsyncSession, user_id: str, area_id: UUID
) -> Optional[CustomAreaOrm]:
    """Get a custom area if this user owns it."""
    result = await session.execute(
        select(CustomAreaOrm).filter_by(id=area_id, user_id=user_id)
    )
    return result.scalars().first()


async def update_custom_area_name(
    session: AsyncSession, area: CustomAreaOrm, name: str
) -> None:
    """Rename a custom area and its mirror."""
    area.name = name
    # Flush so the mirror reads the new name in this same transaction.
    await session.flush()
    await upsert_custom_aoi(session, area_id=area.id)
    await session.refresh(area)


async def delete_custom_area(
    session: AsyncSession, area: CustomAreaOrm
) -> None:
    """Delete a custom area and its mirror.

    The ``user_aois`` foreign key cascades, so no owner link survives the area.
    """
    await delete_custom_aoi(session, area.id)
    await session.delete(area)
