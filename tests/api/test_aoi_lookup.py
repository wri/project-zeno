"""Tests for the by-id AOI read paths over the unified ``aois`` table.

``get_geometry_data`` and ``fetch_aoi_bbox`` both resolve a single AOI by
``(source, src_id)``. These run against the real table rather than mocking the
helper (which is what ``test_geometry.py`` does for the endpoint's error
handling), so the SQL itself is covered.

The custom branch of ``get_geometry_data`` deliberately still reads
``custom_areas`` -- it returns the raw drawn GeoJSON, which the dissolved
``aois.geometry`` cannot reproduce -- so it is asserted here as unchanged.
"""

import pytest

from src.shared.geocoding_helpers import fetch_aoi_bbox, get_geometry_data
from tests.conftest import seed_reference_aoi

AUTH = {"Authorization": "Bearer abc123"}
_USER_ID = "test-user-wri"

_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]]
    ],
}

_OTHER_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[20.0, 20.0], [20.0, 21.0], [21.0, 21.0], [21.0, 20.0], [20.0, 20.0]]
    ],
}


# ---------------------------------------------------------------------------
# get_geometry_data -- reference sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reference_lookup_returns_geometry():
    await seed_reference_aoi("gadm", "IND.2_1", "Andhra Pradesh", "state")

    result = await get_geometry_data("gadm", "IND.2_1")

    assert result["name"] == "Andhra Pradesh"
    assert result["subtype"] == "state"
    assert result["source"] == "gadm"
    assert result["src_id"] == "IND.2_1"
    assert result["geometry"]["type"] == "MultiPolygon"


@pytest.mark.asyncio
async def test_reference_lookup_is_scoped_to_its_source():
    """The same source_id under two sources must not collide."""
    await seed_reference_aoi("gadm", "123", "Gadm Place", "state")
    await seed_reference_aoi("wdpa", "123", "Wdpa Place", "protected-area")

    assert (await get_geometry_data("gadm", "123"))["name"] == "Gadm Place"
    assert (await get_geometry_data("wdpa", "123"))["name"] == "Wdpa Place"


@pytest.mark.asyncio
async def test_reference_lookup_missing_returns_none():
    assert await get_geometry_data("gadm", "NOPE") is None


@pytest.mark.asyncio
async def test_disputed_rows_stay_resolvable_by_id():
    """Search hides disputed rows; this lookup must still resolve them."""
    await seed_reference_aoi(
        "gadm", "Z01", "Disputed Place", "country", is_disputed=True
    )

    result = await get_geometry_data("gadm", "Z01")

    assert result is not None
    assert result["name"] == "Disputed Place"


@pytest.mark.asyncio
async def test_kba_src_id_echoes_back_as_int():
    """KBA ids were numeric pre-unification; the response type is preserved."""
    await seed_reference_aoi(
        "kba", "16595", "Some KBA", "key-biodiversity-area"
    )

    result = await get_geometry_data("kba", "16595")

    assert result["src_id"] == 16595
    assert isinstance(result["src_id"], int)


@pytest.mark.asyncio
async def test_invalid_source_raises():
    with pytest.raises(ValueError, match="Invalid source"):
        await get_geometry_data("not_a_source", "1")


@pytest.mark.asyncio
async def test_source_aliases_are_not_accepted():
    """Aliases are a search-endpoint affordance; this lookup never took them."""
    with pytest.raises(ValueError, match="Invalid source"):
        await get_geometry_data("protectedareas", "1")


# ---------------------------------------------------------------------------
# get_geometry_data -- custom areas (still served from custom_areas)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_lookup_returns_raw_drawn_geometry(auth_override, client):
    """A single-part custom area still returns the bare Polygon it was drawn as.

    Reading it from ``aois`` would return a dissolved MultiPolygon instead; this
    pins the shape the analytics / thumbnail / mosaic consumers see today.
    """
    auth_override(_USER_ID)
    res = await client.post(
        "/api/custom_areas",
        json={"name": "Drawn Area", "geometries": [_POLYGON]},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    area_id = res.json()["id"]

    result = await get_geometry_data("custom", area_id, user_id=_USER_ID)

    assert result["name"] == "Drawn Area"
    assert result["subtype"] == "custom"
    assert result["geometry"] == _POLYGON


@pytest.mark.asyncio
async def test_custom_multipart_lookup_returns_geometry_collection(
    auth_override, client
):
    auth_override(_USER_ID)
    res = await client.post(
        "/api/custom_areas",
        json={
            "name": "Two Parts",
            "geometries": [_POLYGON, _OTHER_POLYGON],
        },
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    area_id = res.json()["id"]

    result = await get_geometry_data("custom", area_id, user_id=_USER_ID)

    assert result["geometry"]["type"] == "GeometryCollection"
    assert result["geometry"]["geometries"] == [_POLYGON, _OTHER_POLYGON]


@pytest.mark.asyncio
async def test_custom_lookup_requires_user_id():
    with pytest.raises(ValueError, match="user_id required"):
        await get_geometry_data(
            "custom", "123e4567-e89b-12d3-a456-426614174000"
        )


@pytest.mark.asyncio
async def test_custom_lookup_rejects_non_uuid():
    with pytest.raises(ValueError, match="Invalid UUID"):
        await get_geometry_data("custom", "not-a-uuid", user_id="u1")


# ---------------------------------------------------------------------------
# fetch_aoi_bbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_bbox_reads_the_stored_bbox():
    """The stored bbox is returned as-is, not re-derived from the geometry."""
    await seed_reference_aoi(
        "wdpa",
        "555",
        "Some Park",
        "protected-area",
        bbox=(-10.5, -20.5, 30.5, 40.5),
    )

    assert await fetch_aoi_bbox("wdpa", "555") == [-10.5, -20.5, 30.5, 40.5]


@pytest.mark.asyncio
async def test_fetch_bbox_for_mirrored_custom_area(auth_override, client):
    """Custom bboxes come from the mirror, so no bespoke JSONB bbox SQL runs."""
    auth_override(_USER_ID)
    res = await client.post(
        "/api/custom_areas",
        json={"name": "Drawn Area", "geometries": [_POLYGON]},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text

    bbox = await fetch_aoi_bbox("custom", res.json()["id"])

    assert bbox == [10.0, 10.0, 11.0, 11.0]


@pytest.mark.asyncio
async def test_fetch_bbox_missing_row_returns_world():
    assert await fetch_aoi_bbox("gadm", "NOPE") == [-180.0, -90.0, 180.0, 90.0]


@pytest.mark.asyncio
async def test_fetch_bbox_null_bbox_returns_world():
    await seed_reference_aoi(
        "landmark", "L1", "No Bbox", "indigenous-and-community-land", bbox=None
    )

    assert await fetch_aoi_bbox("landmark", "L1") == [
        -180.0,
        -90.0,
        180.0,
        90.0,
    ]


@pytest.mark.asyncio
async def test_fetch_bbox_unknown_source_returns_world():
    assert await fetch_aoi_bbox("nope", "1") == [-180.0, -90.0, 180.0, 90.0]
