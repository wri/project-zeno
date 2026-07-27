"""Tests for the Sentinel-2 mosaic service and endpoints."""

import base64
import io
import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError
from cogeo_mosaic.errors import MosaicNotFoundError
from cogeo_mosaic.mosaic import MosaicJSON

import src.api.services.mosaic as mosaic_service
from src.api.services.mosaic import (
    AoiTooLargeError,
    MosaicRecipe,
    MosaicResult,
    NoScenesFoundError,
    _s3_key,
    _s3_uri,
    check_aoi_area,
    create_sentinel2_mosaic,
    decode_recipe,
    encode_recipe,
)
from src.shared.config import SharedSettings

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


class FakeS3Client:
    """Minimal in-memory stand-in for the boto3 S3 client."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.store[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.store[Key])}


@pytest.fixture(autouse=True)
def fake_s3(monkeypatch):
    """Replace the S3 client with an in-memory fake and set mosaic settings."""
    client = FakeS3Client()
    monkeypatch.setattr(mosaic_service, "_s3_client", lambda: client)
    monkeypatch.setattr(SharedSettings, "mosaic_s3_bucket", "test-bucket")
    monkeypatch.setattr(SharedSettings, "mosaic_s3_prefix", "mosaics")
    return client


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


def _load_mosaic_from_s3(s3, token) -> MosaicJSON:
    return MosaicJSON.model_validate_json(s3.store[_s3_key(token)])


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
async def test_create_mosaic_orders_scenes_by_date_proximity(fake_s3):
    far = FakeItem(date(2025, 5, 1), 5.0, "https://example.com/far.tif")
    near = FakeItem(date(2025, 6, 14), 10.0, "https://example.com/near.tif")

    with _patch_geometry(), _patch_search([far, near]):
        result = await create_sentinel2_mosaic(RECIPE)

    assert result.mosaic_id == encode_recipe(RECIPE)
    assert result.item_count == 2
    assert result.date_start == date(2025, 5, 1)
    assert result.date_end == date(2025, 6, 14)

    # The mosaic is persisted to S3.
    assert _s3_key(result.mosaic_id) in fake_s3.store

    # The scene closest to the target date must be first per quadkey, since
    # the mosaic renders the first valid scene.
    mosaic = _load_mosaic_from_s3(fake_s3, result.mosaic_id)
    for assets in mosaic.tiles.values():
        assert assets[0] == "https://example.com/near.tif"


@pytest.mark.asyncio
async def test_create_mosaic_skips_when_exists(fake_s3):
    """A second build for the same recipe finds the mosaic in S3 and reads
    persisted metadata instead of loading geometry, searching STAC, uploading."""
    item = FakeItem(date(2025, 6, 1), 3.0, "https://example.com/a.tif")
    with _patch_geometry(), _patch_search([item]):
        first = await create_sentinel2_mosaic(RECIPE)

    # The mosaic object itself is the cache marker (S3 puts are atomic).
    assert _s3_key(first.mosaic_id) in fake_s3.store

    with _patch_geometry() as geo, _patch_search([item]) as search:
        second = await create_sentinel2_mosaic(RECIPE)

    assert second.mosaic_id == first.mosaic_id
    # On a cache hit, persisted metadata is read from the mosaic JSON.
    assert second.item_count == 1
    assert second.date_start == date(2025, 6, 1)
    assert second.date_end == date(2025, 6, 1)
    assert second.mean_cloud_cover == 3.0
    assert second.min_cloud_cover == 3.0
    assert second.max_cloud_cover == 3.0
    # On a hit we return without loading geometry, searching STAC or uploading.
    geo.assert_not_called()
    search.assert_not_called()


def test_mosaic_result_urls():
    result = MosaicResult(
        mosaic_id="abc123",
        item_count=1,
        date_start=date(2025, 1, 1),
        date_end=date(2025, 1, 2),
    )
    assert result.tile_url == (
        "https://tiles.globalforestwatch.org/cog/mosaic/tiles/WebMercatorQuad"
        "/{z}/{x}/{y}.png"
        "?url=s3%3A%2F%2Ftest-bucket%2Fmosaics%2Fabc123.json"
    )
    assert result.tilejson_url == (
        "https://tiles.globalforestwatch.org/cog/mosaic/WebMercatorQuad"
        "/tilejson.json"
        "?url=s3%3A%2F%2Ftest-bucket%2Fmosaics%2Fabc123.json"
    )
    assert _s3_uri("abc123") == "s3://test-bucket/mosaics/abc123.json"


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
async def test_create_mosaic_success_and_idempotent(
    client, auth_override, fake_s3
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

    # The mosaic is persisted to S3, where the tiler reads it from.
    assert _s3_key(body["mosaic_id"]) in fake_s3.store

    # A second identical create hits S3 and reads persisted metadata.
    with _patch_geometry() as geo, _patch_search([item]) as search:
        response = await client.post(
            "/mosaic/create/gadm/CHE.1_1?target_date=2025-06-15",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    cached = response.json()
    assert cached["mosaic_id"] == body["mosaic_id"]
    # The cache hit reads metadata from the mosaic JSON.
    assert cached["item_count"] == 1
    assert cached["date_start"] == "2025-06-01"
    assert cached["date_end"] == "2025-06-01"
    assert cached["mean_cloud_cover"] == 3.0
    assert cached["min_cloud_cover"] == 3.0
    assert cached["max_cloud_cover"] == 3.0
    geo.assert_not_called()
    search.assert_not_called()


class FakeItemNonNumericCloudCover(FakeItem):
    """A STAC item whose eo:cloud_cover is a non-numeric string."""

    def __init__(self, day: date, href: str):
        self.datetime = datetime(
            day.year, day.month, day.day, tzinfo=timezone.utc
        )
        self.properties = {
            "datetime": self.datetime.isoformat(),
            "eo:cloud_cover": "N/A",
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


# ---------------------------------------------------------------------------
# Metadata extra fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_missing_fields_returns_bare_result(fake_s3):
    """A mosaic written before the metadata fields were added returns
    a bare MosaicResult (graceful degradation)."""
    token = encode_recipe(RECIPE)
    # Write a mosaic JSON without any extra fields.
    fake_s3.store[_s3_key(token)] = json.dumps(
        {
            "mosaic": "0.0.3",
            "tiles": {},
            "minzoom": 8,
            "maxzoom": 14,
        }
    ).encode("utf-8")

    result = await create_sentinel2_mosaic(RECIPE)
    assert result.mosaic_id == token
    assert result.item_count is None
    assert result.date_start is None
    assert result.date_end is None
    assert result.mean_cloud_cover is None


@pytest.mark.asyncio
async def test_cache_hit_corrupt_json_returns_bare_result(fake_s3):
    """A corrupt/unreadable mosaic JSON returns a bare MosaicResult,
    not an error."""
    token = encode_recipe(RECIPE)
    fake_s3.store[_s3_key(token)] = b"{not valid json at all"

    result = await create_sentinel2_mosaic(RECIPE)
    assert result.mosaic_id == token
    assert result.item_count is None
    assert result.date_start is None


@pytest.mark.asyncio
async def test_cache_hit_non_object_json_returns_bare_result(fake_s3):
    """Valid JSON that isn't an object (e.g. a bare array) also degrades to
    a bare MosaicResult rather than raising."""
    token = encode_recipe(RECIPE)
    fake_s3.store[_s3_key(token)] = b"[1, 2, 3]"

    result = await create_sentinel2_mosaic(RECIPE)
    assert result.mosaic_id == token
    assert result.item_count is None
    assert result.date_start is None


@pytest.mark.asyncio
async def test_cloud_cover_stats_computed(fake_s3):
    """Cloud cover stats are computed across multiple scenes with
    varying values."""
    items = [
        FakeItem(date(2025, 6, 1), 5.0, "https://example.com/a.tif"),
        FakeItem(date(2025, 6, 3), 12.0, "https://example.com/b.tif"),
        FakeItem(date(2025, 6, 5), 1.0, "https://example.com/c.tif"),
    ]
    with _patch_geometry(), _patch_search(items):
        result = await create_sentinel2_mosaic(RECIPE)

    assert result.item_count == 3
    assert result.mean_cloud_cover == round((5.0 + 12.0 + 1.0) / 3, 2)
    assert result.min_cloud_cover == 1.0
    assert result.max_cloud_cover == 12.0


@pytest.mark.asyncio
async def test_cloud_cover_ignores_non_numeric_items(fake_s3):
    """Items without a numeric eo:cloud_cover are excluded from stats."""
    items = [
        FakeItem(date(2025, 6, 1), 10.0, "https://example.com/a.tif"),
        FakeItemNonNumericCloudCover(
            date(2025, 6, 3), "https://example.com/b.tif"
        ),
    ]
    with _patch_geometry(), _patch_search(items):
        result = await create_sentinel2_mosaic(RECIPE)

    assert result.item_count == 2
    assert result.mean_cloud_cover == 10.0
    assert result.min_cloud_cover == 10.0
    assert result.max_cloud_cover == 10.0
