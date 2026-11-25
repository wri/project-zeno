"""The user's areas in Postgres: ``user_aois`` rows joined to ``aois``."""

from typing import Optional
from uuid import UUID

from sqlalchemy import (
    RowMapping,
    Select,
    case,
    delete,
    desc,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.data_models import AoiOrm, AoiRelationship, UserAoiOrm


def user_aois_query(user_id: str) -> Select:
    """Build the query for a user's areas, with the fields "My areas" shows."""
    # An owner link may be backfilled long after its custom area was drawn,
    # so an owned area is dated by the area itself; a saved area by when it
    # was saved.
    added_at = case(
        (
            UserAoiOrm.relationship_type == AoiRelationship.OWNER,
            AoiOrm.created_at,
        ),
        else_=UserAoiOrm.created_at,
    )
    return (
        select(
            UserAoiOrm.id,
            UserAoiOrm.relationship_type.label("relationship"),
            func.coalesce(UserAoiOrm.name, AoiOrm.name).label("name"),
            AoiOrm.source,
            AoiOrm.source_id.label("src_id"),
            AoiOrm.subtype,
            AoiOrm.bbox,
            added_at.label("created_at"),
        )
        .join(AoiOrm, AoiOrm.id == UserAoiOrm.aoi_id)
        .where(UserAoiOrm.user_id == user_id)
    )


async def list_user_aois(
    session: AsyncSession, user_id: str, limit: int, offset: int
) -> list[RowMapping]:
    """List a user's areas, newest first."""
    query = (
        user_aois_query(user_id)
        .order_by(desc("created_at"), UserAoiOrm.id)
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(query)).mappings().all())


async def select_user_aoi(
    session: AsyncSession, user_id: str, user_aoi_id: UUID
) -> Optional[RowMapping]:
    """Select one of a user's areas, or None if it isn't theirs."""
    query = user_aois_query(user_id).where(UserAoiOrm.id == user_aoi_id)
    return (await session.execute(query)).mappings().first()


async def select_reference_aoi_id(
    session: AsyncSession, source: str, src_id: str
) -> Optional[UUID]:
    """Select the id of the live ``aois`` row for a source area."""
    return await session.scalar(
        select(AoiOrm.id).where(
            AoiOrm.source == source,
            AoiOrm.source_id == src_id,
            AoiOrm.is_deprecated.is_(False),
        )
    )


async def insert_saved_aoi(
    session: AsyncSession, user_id: str, aoi_id: UUID, name: Optional[str]
) -> Optional[UUID]:
    """Save an area to a user's areas; None if it is already saved."""
    return await session.scalar(
        insert(UserAoiOrm)
        .values(
            user_id=user_id,
            aoi_id=aoi_id,
            relationship_type=AoiRelationship.SAVED,
            name=name,
        )
        .on_conflict_do_nothing(constraint="uq_user_aoi_relationship")
        .returning(UserAoiOrm.id)
    )


async def update_saved_aoi_name(
    session: AsyncSession, user_aoi_id: UUID, name: str
) -> None:
    """Set a user's own label for a saved area."""
    await session.execute(
        update(UserAoiOrm)
        .where(UserAoiOrm.id == user_aoi_id)
        .values(name=name)
    )


async def delete_saved_aoi(session: AsyncSession, user_aoi_id: UUID) -> None:
    """Remove a saved area from a user's areas."""
    await session.execute(
        delete(UserAoiOrm).where(UserAoiOrm.id == user_aoi_id)
    )
