"""SQL fragments that normalize source geometry for the unified ``aois`` table.

Shared by the batch backfill (``build-aois`` in :mod:`src.api.cli`) and the
runtime custom-area mirror (:mod:`src.api.services.aoi_sync`) so the two write
paths cannot drift.
"""

from src.shared.geocoding_helpers import _antimeridian_bbox_sql


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
