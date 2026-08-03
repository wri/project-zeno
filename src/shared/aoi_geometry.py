"""SQL fragments that normalize source geometry for the unified ``aois`` table.

Shared by the batch backfill (``build-aois`` in :mod:`src.api.cli`) and the
runtime custom-area mirror (:mod:`src.api.services.aoi_sync`) so the two write
paths cannot drift.
"""


def _antimeridian_bbox_sql(geom_expr: str) -> str:
    """
    Returns [west, south, east, north] JSON array.
    For antimeridian-crossing geometries (span > 180°), clips to each
    half-plane to get the bbox of the eastern and western parts separately —
    no ST_Dump, no vertex iteration. Falls back to naive bbox if either
    clip returns nothing (geometry doesn't truly cross the antimeridian).
    """
    east_half = "ST_MakeEnvelope(0, -90, 180, 90, 4326)"
    west_half = "ST_MakeEnvelope(-180, -90, 0, 90, 4326)"
    return f"""
    CASE
        WHEN ST_XMax({geom_expr}) - ST_XMin({geom_expr}) > 180
        THEN (
            SELECT COALESCE(
                CASE
                    WHEN west IS NOT NULL AND east IS NOT NULL
                    THEN json_build_array(west, ST_YMin({geom_expr}), east, ST_YMax({geom_expr}))
                END,
                json_build_array(ST_XMin({geom_expr}), ST_YMin({geom_expr}), ST_XMax({geom_expr}), ST_YMax({geom_expr}))
            )
            FROM (
                SELECT
                    ST_XMin(ST_Envelope(ST_ClipByBox2D({geom_expr}, {east_half}))) AS west,
                    ST_XMax(ST_Envelope(ST_ClipByBox2D({geom_expr}, {west_half}))) AS east
            ) AS parts
        )
        ELSE json_build_array(
            ST_XMin({geom_expr}),
            ST_YMin({geom_expr}),
            ST_XMax({geom_expr}),
            ST_YMax({geom_expr})
        )
    END
    """


def multipolygon_sql(geom_expr: str) -> str:
    """Normalize *geom_expr* to a valid 2D MultiPolygon (for the typed column).

    ``ST_MakeValid`` repairs self-intersections / ring errors;
    ``ST_CollectionExtract(..., 3)`` keeps only polygonal parts (dropping the
    line/point slivers ``ST_MakeValid`` can emit); ``ST_Multi`` guarantees the
    ``MULTIPOLYGON`` type the ``aois.geometry`` column enforces. Callers filter
    out an empty result (a geometry with no areal component) with
    ``NOT ST_IsEmpty(...)`` so such rows are skipped, not stored empty.

    The repair runs per part (``ST_Dump`` -> ``ST_MakeValid`` ->
    ``ST_Collect``): on a whole MultiPolygon ``ST_MakeValid`` resolves every
    ring against every other in one GEOS overlay, whose cost scales with part
    count and can exhaust the backend on many-part rows. The tradeoff is that
    overlaps *between* parts go unresolved, so the result is not guaranteed
    OGC-valid -- fine here, as the column enforces type but not validity.
    """
    return (
        "ST_Multi(ST_CollectionExtract("
        "(SELECT ST_Collect(ST_MakeValid(d.geom)) "
        f"FROM ST_Dump(ST_Force2D({geom_expr})) d), 3))"
    )


def bbox_float_array_sql(geom_expr: str) -> str:
    """A ``float8[]`` ``[west, south, east, north]`` for *geom_expr*.

    Wraps the shared antimeridian-aware bbox (which yields a JSON array) and
    turns it into a real Postgres array so it lands in ``aois.bbox`` directly.
    ``WITH ORDINALITY`` pins the element order.
    """
    return (
        "(SELECT array_agg(e::double precision ORDER BY ord) "
        f"FROM json_array_elements_text({_antimeridian_bbox_sql(geom_expr)}) "
        "WITH ORDINALITY AS t(e, ord))"
    )


# The dissolved union of a ``custom_areas.geometries`` JSONB list, coerced to a
# valid MultiPolygon. ``ST_Union`` dissolves overlapping user-drawn parts (so
# ``area_km2`` is not double-counted); ``ST_MakeValid`` per element guards
# invalid input polygons. Expects ``ca`` to be the ``custom_areas`` alias in
# scope.
CUSTOM_AREA_GEOM_SQL = multipolygon_sql(
    "(SELECT ST_Union("
    "ST_MakeValid(ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(g), 4326)))"
    ") FROM jsonb_array_elements_text(ca.geometries) AS g)"
)
