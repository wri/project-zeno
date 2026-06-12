"""Tests for the Sentinel-2 mosaic service and endpoints."""

import base64
import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from cogeo_mosaic.errors import MosaicNotFoundError

from src.api.services.mosaic import (
    AoiTooLargeError,
    InMemoryBackend,
    MosaicRecipe,
    MosaicResult,
    NoScenesFoundError,
    _mosaic_store,
    check_aoi_area,
    create_sentinel2_mosaic,
    decode_recipe,
    encode_recipe,
)

REGIONAL_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[8.0, 46.8], [9.0, 46.8], [9.0, 47.5], [8.0, 47.5], [8.0, 46.8]]
    ],
}

CONTINENTAL_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-74, -34], [-34, -34], [-34, 5], [-74, 5], [-74, -34]]],
}

RECIPE = MosaicRecipe(
    aois=(("gadm", "CHE.26_1"),), target_date=date(2025, 6, 15)
)


class FakeItem:
    """Minimal stand-in for a pystac Item from earth-search."""

    def __init__(self, day: date, cloud_cover: float, href: str):
        self.datetime = datetime(
            day.year, day.month, day.day, tzinfo=timezone.utc
        )
        self.properties = {
            "datetime": self.datetime.isoformat(),
            "eo:cloud_cover": cloud_cover,
        }
        self._href = href

    def to_dict(self):
        return {
            "type": "Feature",
            "geometry": REGIONAL_POLYGON,
            "bbox": [8.0, 46.8, 9.0, 47.5],
            "properties": self.properties,
            "assets": {"visual": {"href": self._href}},
        }


def _patch_search(items):
    """Patch the STAC client so a search returns the given items."""
    fake_search = type("S", (), {"items": lambda self: iter(items)})()
    fake_catalog = type(
        "C", (), {"search": lambda self, **kwargs: fake_search}
    )()
    return patch(
        "src.api.services.mosaic.pystac_client.Client.open",
        return_value=fake_catalog,
    )


def _patch_geometry(geometry=REGIONAL_POLYGON):
    """Patch the AOI geometry lookup inside the mosaic service."""
    return patch(
        "src.api.services.mosaic.get_geometry_data",
        new_callable=AsyncMock,
        return_value={"geometry": geometry} if geometry else None,
    )


# ---------------------------------------------------------------------------
# Recipe tokens
# ---------------------------------------------------------------------------


def test_recipe_token_roundtrip():
    recipe = MosaicRecipe(
        aois=(("gadm", "CHE.26_1"), ("custom", "abc")),
        target_date=date(2025, 6, 15),
        window_days=45,
        max_cloud_cover=10,
        max_items=20,
        user_id="user-1",
    )
    assert decode_recipe(encode_recipe(recipe)) == recipe


def test_recipe_token_is_deterministic():
    assert encode_recipe(RECIPE) == encode_recipe(RECIPE)


def test_decode_rejects_malformed_token():
    token = encode_recipe(RECIPE)
    with pytest.raises(MosaicNotFoundError):
        decode_recipe(token[:-2] + "xx")
    with pytest.raises(MosaicNotFoundError):
        decode_recipe("garbage")


def test_decode_clamps_parameters():
    payload = {
        "a": [["gadm", "X"]],
        "d": "2025-06-15",
        "w": 9999,
        "c": 500,
        "n": 100000,
    }
    token = (
        base64.urlsafe_b64encode(json.dumps(payload).encode())
        .decode()
        .rstrip("=")
    )
    recipe = decode_recipe(token)
    assert recipe.window_days == 183
    assert recipe.max_cloud_cover == 100
    assert recipe.max_items == 100


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_check_aoi_area_accepts_regional():
    assert check_aoi_area(REGIONAL_POLYGON) < 50_000


def test_check_aoi_area_rejects_continental():
    with pytest.raises(AoiTooLargeError):
        check_aoi_area(CONTINENTAL_POLYGON)


@pytest.mark.asyncio
async def test_create_mosaic_missing_geometry():
    with _patch_geometry(None):
        with pytest.raises(MosaicNotFoundError):
            await create_sentinel2_mosaic(RECIPE)


@pytest.mark.asyncio
async def test_create_mosaic_no_scenes():
    with _patch_geometry(), _patch_search([]):
        with pytest.raises(NoScenesFoundError):
            await create_sentinel2_mosaic(RECIPE)


@pytest.mark.asyncio
async def test_create_mosaic_orders_scenes_by_date_proximity():
    far = FakeItem(date(2025, 5, 1), 5.0, "https://example.com/far.tif")
    near = FakeItem(date(2025, 6, 14), 10.0, "https://example.com/near.tif")

    with _patch_geometry(), _patch_search([far, near]):
        result = await create_sentinel2_mosaic(RECIPE)

    assert result.mosaic_id == encode_recipe(RECIPE)
    assert result.item_count == 2
    assert result.date_start == date(2025, 5, 1)
    assert result.date_end == date(2025, 6, 14)

    # The scene closest to the target date must be first per quadkey, since
    # the mosaic renders the first valid scene.
    mosaic = _mosaic_store[result.mosaic_id]
    for assets in mosaic.tiles.values():
        assert assets[0] == "https://example.com/near.tif"


def test_backend_unknown_mosaic_raises_not_found():
    with pytest.raises(MosaicNotFoundError):
        InMemoryBackend("does-not-exist")


def test_mosaic_result_urls():
    result = MosaicResult(
        mosaic_id="abc123",
        item_count=1,
        date_start=date(2025, 1, 1),
        date_end=date(2025, 1, 2),
    )
    assert result.tile_url == (
        "/mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=abc123"
    )
    assert result.tilejson_url == (
        "/mosaic/WebMercatorQuad/tilejson.json?url=abc123"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_mosaic_requires_auth(client):
    response = await client.post("/mosaic/create/gadm/IND.1_1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_mosaic_geometry_not_found(client, auth_override):
    auth_override("test-user-1")

    with _patch_geometry(None):
        response = await client.post(
            "/mosaic/create/gadm/DOES_NOT_EXIST",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 404
    assert "Geometry not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_mosaic_aoi_too_large(client, auth_override):
    auth_override("test-user-1")

    with _patch_geometry(CONTINENTAL_POLYGON):
        response = await client.post(
            "/mosaic/create/gadm/BRA",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 422
    assert "too large" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_mosaic_success_and_rebuild_on_cold_cache(
    client, auth_override
):
    auth_override("test-user-1")
    item = FakeItem(date(2025, 6, 1), 3.0, "https://example.com/a.tif")

    with _patch_geometry(), _patch_search([item]):
        response = await client.post(
            "/mosaic/create/gadm/CHE.1_1?target_date=2025-06-15",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["item_count"] == 1
        assert body["date_start"] == "2025-06-01"

        # The cached mosaic is served through the titiler endpoints.
        tilejson = await client.get(
            f"/mosaic/WebMercatorQuad/tilejson.json?url={body['mosaic_id']}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert tilejson.status_code == 200
        assert tilejson.json()["minzoom"] == 8

        # A cold cache (restart, other worker) rebuilds from the token.
        _mosaic_store.clear()
        tilejson = await client.get(
            f"/mosaic/WebMercatorQuad/tilejson.json?url={body['mosaic_id']}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert tilejson.status_code == 200
        assert body["mosaic_id"] in _mosaic_store


@pytest.mark.asyncio
async def test_tilejson_requires_auth(client):
    token = encode_recipe(RECIPE)
    response = await client.get(
        f"/mosaic/WebMercatorQuad/tilejson.json?url={token}"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tilejson_invalid_token_returns_404(client, auth_override):
    auth_override("test-user-1")
    response = await client.get(
        "/mosaic/WebMercatorQuad/tilejson.json?url=unknown",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404
