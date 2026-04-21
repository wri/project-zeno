from src.agent.tools.pick_aoi.tool import _antimeridian_bbox_sql


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
