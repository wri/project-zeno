"""Unit tests for the SQL fragments of the build path. They check the string
only, and use no database.

The build computes the antimeridian bbox once, and no read path composes it, so
these tests belong with the other ``aoi_geometry`` fragments.
"""

from src.shared.aoi_geometry import (
    CUSTOM_AREA_GEOM_SQL,
    _antimeridian_bbox_sql,
    bbox_float_array_sql,
    multipolygon_sql,
)


def test_sql_contains_crossing_condition():
    sql = _antimeridian_bbox_sql("geometry")
    assert "ST_XMax(geometry) - ST_XMin(geometry) > 180" in sql


def test_sql_clips_to_east_and_west_half_planes():
    sql = _antimeridian_bbox_sql("geometry")
    assert "ST_MakeEnvelope(0, -90, 180, 90, 4326)" in sql
    assert "ST_MakeEnvelope(-180, -90, 0, 90, 4326)" in sql


def test_sql_has_fallback_branch():
    sql = _antimeridian_bbox_sql("geometry")
    assert "ELSE json_build_array" in sql


def test_sql_custom_geom_expr():
    sql = _antimeridian_bbox_sql("bounds.geometry")
    assert "bounds.geometry" in sql
    assert "geometry" not in sql.replace("bounds.geometry", "")


def test_sql_uses_west_xmin_and_east_xmax():
    sql = _antimeridian_bbox_sql("geometry")
    assert "ST_XMin(ST_Envelope(ST_ClipByBox2D" in sql
    assert "ST_XMax(ST_Envelope(ST_ClipByBox2D" in sql


def test_bbox_float_array_wraps_the_json_bbox():
    """The float8[] wrapper must keep the element order, and not only
    aggregate."""
    sql = bbox_float_array_sql("geom")
    assert "json_array_elements_text" in sql
    assert "WITH ORDINALITY" in sql
    assert "ORDER BY ord" in sql


def test_multipolygon_sql_repairs_per_part():
    """ST_MakeValid runs on each part, and not once over the MultiPolygon."""
    sql = multipolygon_sql("geometry")
    assert "ST_Dump" in sql
    assert "ST_MakeValid(d.geom)" in sql
    # CollectionExtract(..., 3) removes the line and point slivers that
    # MakeValid produces.
    assert "ST_CollectionExtract" in sql
    assert "ST_Multi" in sql


def test_custom_area_geom_dissolves_the_drawn_parts():
    """ST_Union runs, so two overlapping drawn parts do not count twice in
    area_km2."""
    assert "ST_Union" in CUSTOM_AREA_GEOM_SQL
    assert "jsonb_array_elements_text(ca.geometries)" in CUSTOM_AREA_GEOM_SQL
