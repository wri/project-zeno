"""The user's area library in Postgres: ``user_aois`` rows joined to ``aois``."""

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

# An owner link may be backfilled long after its custom area was drawn, so an
# owned area is dated by the area itself; a saved area by when it was saved.
LIST_USER_AOIS_SQL = text(
    """
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
    ORDER BY created_at DESC, ua.id
    LIMIT :limit OFFSET :offset
    """
)


async def list_user_aois(
    session: AsyncSession, user_id: str, limit: int, offset: int
) -> list[RowMapping]:
    """List a user's library entries, newest first."""
    result = await session.execute(
        LIST_USER_AOIS_SQL,
        {"user_id": user_id, "limit": limit, "offset": offset},
    )
    return list(result.mappings().all())
