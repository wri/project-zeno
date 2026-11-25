"""The user's areas in Postgres: ``user_aois`` rows joined to ``aois``."""

from typing import Optional
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

# An owner link may be backfilled long after its custom area was drawn, so an
# owned area is dated by the area itself; a saved area by when it was saved.
USER_AOI_SELECT = """
    SELECT
        ua.id,
        ua.relationship,
        COALESCE(ua.name, a.name) AS name,
        a.source,
        a.source_id AS src_id,
        a.subtype,
        a.bbox,
        CASE WHEN ua.relationship = 'owner' THEN a.created_at
             ELSE ua.created_at END AS created_at
    FROM user_aois ua
    JOIN aois a ON a.id = ua.aoi_id
    WHERE ua.user_id = :user_id
"""

LIST_USER_AOIS_SQL = text(
    USER_AOI_SELECT
    + """
    ORDER BY created_at DESC, ua.id
    LIMIT :limit OFFSET :offset
    """
)

SELECT_USER_AOI_SQL = text(USER_AOI_SELECT + " AND ua.id = :user_aoi_id")

SELECT_REFERENCE_AOI_ID_SQL = text(
    """
    SELECT id FROM aois
    WHERE source = :source AND source_id = :src_id AND NOT is_deprecated
    """
)

INSERT_SAVED_AOI_SQL = text(
    """
    INSERT INTO user_aois (user_id, aoi_id, relationship, name)
    VALUES (:user_id, :aoi_id, 'saved', :name)
    ON CONFLICT (user_id, aoi_id, relationship) DO NOTHING
    RETURNING id
    """
)


async def list_user_aois(
    session: AsyncSession, user_id: str, limit: int, offset: int
) -> list[RowMapping]:
    """List a user's areas, newest first."""
    result = await session.execute(
        LIST_USER_AOIS_SQL,
        {"user_id": user_id, "limit": limit, "offset": offset},
    )
    return list(result.mappings().all())


async def select_user_aoi(
    session: AsyncSession, user_id: str, user_aoi_id: UUID
) -> Optional[RowMapping]:
    """Select one of a user's areas, or None if it isn't theirs."""
    result = await session.execute(
        SELECT_USER_AOI_SQL, {"user_id": user_id, "user_aoi_id": user_aoi_id}
    )
    return result.mappings().first()


async def select_reference_aoi_id(
    session: AsyncSession, source: str, src_id: str
) -> Optional[UUID]:
    """Select the id of the live ``aois`` row for a source area."""
    return await session.scalar(
        SELECT_REFERENCE_AOI_ID_SQL, {"source": source, "src_id": src_id}
    )


async def insert_saved_aoi(
    session: AsyncSession, user_id: str, aoi_id: UUID, name: Optional[str]
) -> Optional[UUID]:
    """Save an area to a user's areas; None if it is already saved."""
    return await session.scalar(
        INSERT_SAVED_AOI_SQL,
        {"user_id": user_id, "aoi_id": aoi_id, "name": name},
    )


async def update_saved_aoi_name(
    session: AsyncSession, user_aoi_id: UUID, name: str
) -> None:
    """Set a user's own label for a saved area."""
    await session.execute(
        text(
            "UPDATE user_aois SET name = :name, updated_at = now() "
            "WHERE id = :user_aoi_id"
        ),
        {"user_aoi_id": user_aoi_id, "name": name},
    )


async def delete_saved_aoi(session: AsyncSession, user_aoi_id: UUID) -> None:
    """Remove a saved area from a user's areas."""
    await session.execute(
        text("DELETE FROM user_aois WHERE id = :user_aoi_id"),
        {"user_aoi_id": user_aoi_id},
    )
