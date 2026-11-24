"""Find custom areas that are copies of a source area, read-only.

Before source areas could be saved by reference, saving a GADM, WDPA, KBA or
LandMark area copied its geometry into a new custom area. Nothing records
where a copy came from, so this matches each custom area's mirror in ``aois``
against the live source areas by geometry. It also lists custom areas with no
mirror, because the user's library is built from the mirror.
"""

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

COPY_REPORT_COLUMNS = (
    "custom_area_id",
    "user_id",
    "name",
    "finding",
    "ref_source",
    "ref_src_id",
    "ref_subtype",
    "name_matches",
    "dashboards",
    "subscriptions",
)

# Candidates are pruned with the GiST index (&&) and by area before the costly
# symmetric difference. Both sides' areas are computed by the same geodesic
# formula, so a copy is not missed through rounding in a stored area.
LIST_SOURCE_AREA_COPIES_SQL = text(
    """
    WITH custom AS (
        SELECT
            a.source_id AS custom_area_id,
            a.created_by AS user_id,
            a.name,
            a.geometry,
            ST_Area(a.geometry::geography) AS area_m2
        FROM aois a
        WHERE a.source = 'custom' AND NOT a.is_deprecated
    ),
    copies AS (
        SELECT
            c.custom_area_id,
            c.user_id,
            c.name,
            'copy' AS finding,
            best.source AS ref_source,
            best.source_id AS ref_src_id,
            best.subtype AS ref_subtype,
            lower(c.name) = lower(best.name) AS name_matches
        FROM custom c
        CROSS JOIN LATERAL (
            SELECT
                r.source,
                r.source_id,
                r.subtype,
                r.name,
                ST_Area(ST_SymDifference(r.geometry, c.geometry)::geography)
                    / NULLIF(c.area_m2, 0) AS difference
            FROM aois r
            WHERE r.source <> 'custom'
              AND NOT r.is_deprecated
              AND r.geometry && c.geometry
              AND abs(ST_Area(r.geometry::geography) - c.area_m2)
                  <= :tolerance * c.area_m2
            ORDER BY difference
            LIMIT 1
        ) best
        WHERE best.difference <= :tolerance
    ),
    not_in_library AS (
        SELECT
            ca.id::text AS custom_area_id,
            ca.user_id,
            ca.name,
            'not_in_library' AS finding,
            NULL AS ref_source,
            NULL AS ref_src_id,
            NULL AS ref_subtype,
            NULL::boolean AS name_matches
        FROM custom_areas ca
        WHERE NOT EXISTS (
            SELECT 1 FROM aois a
            WHERE a.source = 'custom' AND a.source_id = ca.id::text
        )
    ),
    findings AS (
        SELECT * FROM copies
        UNION ALL
        SELECT * FROM not_in_library
    )
    SELECT
        f.*,
        (SELECT count(*) FROM dashboard_aois d
         WHERE d.source = 'custom' AND d.src_id = f.custom_area_id)
            AS dashboards,
        (SELECT count(*) FROM subscriptions s
         JOIN dashboard_aois d ON d.id = s.aoi_id
         WHERE d.source = 'custom' AND d.src_id = f.custom_area_id)
            AS subscriptions
    FROM findings f
    ORDER BY f.finding, f.user_id, f.custom_area_id
    """
)


async def list_source_area_copies(
    session: AsyncSession, tolerance: float
) -> list[RowMapping]:
    """List custom areas that copy a source area, and those not in a library.

    ``tolerance`` is the largest share of the area by which a copy's area and
    its symmetric difference with the source area may differ.
    """
    result = await session.execute(
        LIST_SOURCE_AREA_COPIES_SQL, {"tolerance": tolerance}
    )
    return list(result.mappings().all())
