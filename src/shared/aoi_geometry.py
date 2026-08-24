"""SQL fragments that normalize source geometry for the unified ``aois`` table.

The batch backfill (``build-aois`` in :mod:`src.api.cli`) and the runtime
custom-area mirror (:mod:`src.api.services.aoi_sync`) share these fragments, so
the two write paths cannot diverge.
"""


def _antimeridian_bbox_sql(geom_expr: str) -> str:
    """Return a JSON array of [west, south, east, north].

    A geometry that spans more than 180 degrees can cross the antimeridian. The
    SQL then clips the geometry to each half-plane, and takes the bbox of the
    eastern part and the western part separately. This needs no ST_Dump and no
    iteration over vertices. If either clip returns nothing, the geometry does
    not cross the antimeridian, and the SQL uses the simple bbox.

    Two limits matter to a caller. The span test is a heuristic, so a wide
    extent that does not cross the antimeridian is misclassified. Antarctica is
    one such extent. The crossing branch also returns ``west`` greater than
    ``east`` on purpose, which is the GeoJSON convention. A caller that builds
    a rectangle from the four numbers in order gets an inverted rectangle.
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
    """Normalize *geom_expr* to a valid 2D MultiPolygon for the typed column.

    ``ST_MakeValid`` repairs self-intersections and ring errors.
    ``ST_CollectionExtract(..., 3)`` keeps only the polygonal parts, and removes
    the line and point slivers that ``ST_MakeValid`` can produce. ``ST_Multi``
    gives the ``MULTIPOLYGON`` type that the ``aois.geometry`` column requires. A
    geometry with no areal component gives an empty result. Callers remove such
    rows with ``NOT ST_IsEmpty(...)``, so no row is stored empty.

    The repair runs on each part: ``ST_Dump``, then ``ST_MakeValid``, then
    ``ST_Collect``. On a whole MultiPolygon, ``ST_MakeValid`` resolves every ring
    against every other ring in one GEOS overlay. That cost increases with the
    number of parts and can exhaust the backend. The tradeoff is that an overlap
    between two parts remains, so the result can be invalid for OGC. This is
    acceptable, because the column enforces the type and not the validity.
    """
    return (
        "ST_Multi(ST_CollectionExtract("
        "(SELECT ST_Collect(ST_MakeValid(d.geom)) "
        f"FROM ST_Dump(ST_Force2D({geom_expr})) d), 3))"
    )


def bbox_float_array_sql(geom_expr: str) -> str:
    """Return a ``float8[]`` of ``[west, south, east, north]`` for *geom_expr*.

    The antimeridian-aware bbox gives a JSON array. This fragment converts it to
    a Postgres array, which ``aois.bbox`` accepts directly. ``WITH ORDINALITY``
    keeps the element order.
    """
    return (
        "(SELECT array_agg(e::double precision ORDER BY ord) "
        f"FROM json_array_elements_text({_antimeridian_bbox_sql(geom_expr)}) "
        "WITH ORDINALITY AS t(e, ord))"
    )


# The union of a ``custom_areas.geometries`` JSONB list, as a valid
# MultiPolygon. ``ST_Union`` dissolves the overlaps between user-drawn parts, so
# ``area_km2`` does not count an overlap twice. ``ST_MakeValid`` on each element
# repairs an invalid input polygon. The SQL needs ``ca`` in scope as the alias of
# ``custom_areas``.
CUSTOM_AREA_GEOM_SQL = multipolygon_sql(
    "(SELECT ST_Union("
    "ST_MakeValid(ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(g), 4326)))"
    ") FROM jsonb_array_elements_text(ca.geometries) AS g)"
)
