"""Rename and delete a user's custom area together with its ``aois`` mirror.

Each function commits, so the caller can notify the analytics API afterwards,
outside the transaction.
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


async def rename_custom_area_and_mirror(
    session: AsyncSession, area: CustomAreaOrm, name: str
) -> CustomAreaOrm:
    """Rename a custom area and its mirror, and commit."""
    area.name = name
    await session.flush()
    await upsert_custom_aoi(session, area_id=area.id)
    await session.refresh(area)
    await session.commit()
    return area


async def delete_custom_area_and_mirror(
    session: AsyncSession, area: CustomAreaOrm
) -> None:
    """Delete a custom area and its mirror, and commit.

    The ``user_aois`` foreign key cascades, so no owner link survives the area.
    """
    await delete_custom_aoi(session, area.id)
    await session.delete(area)
    await session.commit()
