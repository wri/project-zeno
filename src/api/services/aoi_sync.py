"""Mirror ``custom_areas`` rows into the unified ``aois`` / ``user_aois`` tables.

``custom_areas`` remains the source of truth for the user-drawn GeoJSON list. The
``aois`` row is the searchable and spatial projection of that list. The same SQL
serves the batch backfill (``build-aois --source custom``) and the write-through
from the CRUD endpoints, so the backfill cannot disagree with what the API wrote.

The caller controls the transaction. These functions execute statements, but they
do not commit, so the mirror and the ``custom_areas`` write are atomic together.

The write-through keeps the mirror correct for each API call.
``build-aois --source custom --prune`` repairs a mirror that went out of step.
The first such gap is every delete that happened before the write-through
existed. A direct database delete, or a failed deploy, opens the same gap.
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
    """Build the custom-area upsert. *scoped* limits it to one ``ca.id``."""
    where_area = "WHERE ca.id = :area_id" if scoped else ""
    return f"""
        WITH collected AS (
            SELECT
                ca.id,
                ca.user_id,
                ca.name,
                ca.properties,
                ca.created_at,
                ca.updated_at,
                {CUSTOM_AREA_GEOM_SQL} AS geom
            FROM custom_areas ca
            {where_area}
        ),
        ins AS (
            INSERT INTO aois (
                source, source_id, name, subtype, geometry,
                bbox, area_km2, properties, created_by, created_at, updated_at
            )
            SELECT
                'custom',
                id::text,
                name,
                'custom-area',
                geom,
                {bbox_float_array_sql("geom")},
                ST_Area(geom::geography) / 1e6,
                properties,
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
                properties = EXCLUDED.properties,
                updated_at = now()
            RETURNING id AS aoi_id, created_by AS user_id
        )
        INSERT INTO user_aois (user_id, aoi_id, relationship)
        SELECT user_id, aoi_id, 'owner' FROM ins
        ON CONFLICT (user_id, aoi_id, relationship) DO NOTHING
    """


# Count the custom areas whose geometry does not give a non-empty MultiPolygon.
# Only the unscoped backfill uses this query, because it derives the shape twice.
# That cost is acceptable once for the whole table, but not for each CRUD call.
# The scoped path uses the index probe below.
_SKIPPED_SQL = f"""
    SELECT count(*) FROM custom_areas ca
    WHERE ca.name IS NOT NULL
      AND ({CUSTOM_AREA_GEOM_SQL} IS NULL
           OR ST_IsEmpty({CUSTOM_AREA_GEOM_SQL}))
"""

# Check if the upsert wrote a row for this area. A `rowcount` of 0 does not show
# that the area was skipped, because the owner link uses ON CONFLICT DO NOTHING
# and a repeated patch correctly inserts no link. This query reads the unique
# index instead.
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
    """Project ``custom_areas`` into ``aois``, with one ``owner`` link for each.

    This function is idempotent. With *area_id* it projects only that area, which
    is the CRUD write-through. Without *area_id* it projects every custom area,
    which is the backfill. It returns the number of owner links upserted.

    A geometry with no areal component is skipped, and not stored empty. The
    ``custom_areas`` row still exists and the CRUD call still succeeds, but the
    area is not searchable. The scoped path logs a warning. The backfill prints a
    count to the CLI.
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
    """Delete the mirrored ``aois`` row. The ``user_aois`` foreign key cascades."""
    await session.execute(
        text(
            "DELETE FROM aois WHERE source = 'custom' AND source_id = :src_id"
        ),
        {"src_id": str(area_id)},
    )


# Find the mirrored rows that have no ``custom_areas`` row. ``aois.source_id`` is
# text and ``custom_areas.id`` is a uuid, so the join casts the uuid to text. The
# cast runs on the uuid side on purpose. The reverse cast raises an error on a
# ``source_id`` that is not a uuid, and one such row would stop the whole delete.
_PRUNE_SQL = """
    DELETE FROM aois
    WHERE source = 'custom'
      AND NOT EXISTS (
          SELECT 1 FROM custom_areas ca WHERE ca.id::text = aois.source_id
      )
"""


async def prune_orphan_custom_aois(session: AsyncSession) -> int:
    """Delete each mirrored ``aois`` row that has no ``custom_areas`` row.

    A row becomes an orphan if a custom area is deleted while the mirror does not
    run. It then appears in search, and the selection of it fails. This function
    deletes the row, as ``delete_custom_aoi`` does, and the ``user_aois`` foreign
    key cascades.

    The caller controls the transaction, so ``--dry-run`` can roll the delete
    back. It returns the number of rows deleted.
    """
    result = await session.execute(text(_PRUNE_SQL))
    return result.rowcount
