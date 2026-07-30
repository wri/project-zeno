"""Mirror ``custom_areas`` rows into the unified ``aois`` / ``user_aois`` tables.

``custom_areas`` stays the source of truth for the user-drawn GeoJSON list; the
``aois`` row is the searchable/spatial projection of it. The same SQL serves the
batch backfill (``build-aois --source custom``) and the per-area write-through
from the CRUD endpoints, so a re-run of the backfill can never disagree with
what the API wrote.

Callers are responsible for the transaction: these functions execute but never
commit, so the mirror lands atomically with the ``custom_areas`` write.
"""

from typing import Optional
from uuid import UUID

import click
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.aoi_geometry import (
    CUSTOM_AREA_GEOM_SQL,
    bbox_float_array_sql,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _upsert_sql(scoped: bool) -> str:
    """Build the custom-area upsert; *scoped* limits it to one ``ca.id``."""
    where_area = "WHERE ca.id = :area_id" if scoped else ""
    return f"""
        WITH collected AS (
            SELECT
                ca.id,
                ca.user_id,
                ca.name,
                ca.created_at,
                ca.updated_at,
                {CUSTOM_AREA_GEOM_SQL} AS geom
            FROM custom_areas ca
            {where_area}
        ),
        ins AS (
            INSERT INTO aois (
                source, source_id, name, subtype, geometry,
                bbox, area_km2, created_by, created_at, updated_at
            )
            SELECT
                'custom',
                id::text,
                name,
                'custom-area',
                geom,
                {bbox_float_array_sql("geom")},
                ST_Area(geom::geography) / 1e6,
                user_id,
                created_at,
                updated_at
            FROM collected
            WHERE name IS NOT NULL AND geom IS NOT NULL AND NOT ST_IsEmpty(geom)
            ON CONFLICT (source, source_id) WHERE NOT is_deprecated
            DO UPDATE SET
                name = EXCLUDED.name,
                geometry = EXCLUDED.geometry,
                bbox = EXCLUDED.bbox,
                area_km2 = EXCLUDED.area_km2,
                updated_at = now()
            RETURNING id AS aoi_id, created_by AS user_id
        )
        INSERT INTO user_aois (user_id, aoi_id, relationship)
        SELECT user_id, aoi_id, 'owner' FROM ins
        ON CONFLICT (user_id, aoi_id, relationship) DO NOTHING
    """


# Count custom areas whose geometry won't coerce to a non-empty MultiPolygon.
# Only used by the unscoped backfill: it re-derives the shape (twice), which is
# affordable once over the whole table but not per CRUD call -- the scoped path
# uses the index probe below instead.
_SKIPPED_SQL = f"""
    SELECT count(*) FROM custom_areas ca
    WHERE ca.name IS NOT NULL
      AND ({CUSTOM_AREA_GEOM_SQL} IS NULL
           OR ST_IsEmpty({CUSTOM_AREA_GEOM_SQL}))
"""

# Did the upsert actually land a row for this area? A `rowcount` of 0 doesn't
# mean it was skipped (the owner link is ON CONFLICT DO NOTHING, so a repeat
# patch legitimately inserts no link), hence a direct check on the unique index.
_MIRRORED_SQL = """
    SELECT EXISTS (
        SELECT 1 FROM aois
        WHERE source = 'custom' AND source_id = :src_id AND NOT is_deprecated
    )
"""


async def upsert_custom_aoi(
    session: AsyncSession,
    *,
    area_id: Optional[UUID] = None,
) -> int:
    """Project ``custom_areas`` into ``aois`` + one ``owner`` link each.

    Idempotent. With *area_id* only that area is projected (the CRUD
    write-through); without it, every custom area is (the backfill). Returns the
    owner-link upsert count.

    A geometry that yields no areal component is skipped rather than stored
    empty -- the ``custom_areas`` row still exists and the CRUD call still
    succeeds, the area just isn't searchable. The scoped path logs that; the
    backfill echoes a count to the CLI.
    """
    scoped = area_id is not None
    params = {"area_id": area_id} if scoped else {}

    result = await session.execute(text(_upsert_sql(scoped)), params)

    if scoped:
        mirrored = await session.scalar(
            text(_MIRRORED_SQL), {"src_id": str(area_id)}
        )
        if not mirrored:
            logger.warning(
                "Custom area not mirrored into aois: geometries not "
                "coercible to a non-empty MultiPolygon.",
                custom_area_id=str(area_id),
            )
    else:
        skipped = await session.scalar(text(_SKIPPED_SQL))
        if skipped:
            click.echo(
                f"⚠️  custom: {skipped} area(s) skipped "
                "(geometries not coercible to a non-empty MultiPolygon)."
            )

    return result.rowcount


async def delete_custom_aoi(session: AsyncSession, area_id: UUID) -> None:
    """Drop the mirrored ``aois`` row; the ``user_aois`` FK cascades."""
    await session.execute(
        text(
            "DELETE FROM aois WHERE source = 'custom' AND source_id = :src_id"
        ),
        {"src_id": str(area_id)},
    )
