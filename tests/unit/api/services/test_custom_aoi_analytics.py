import json
from uuid import uuid4

import httpx
import pytest
import structlog

from src.api.data_models import CustomAreaOrm
from src.api.services.custom_aoi_analytics import (
    AnalyticsCustomAoiStore,
    CustomAoiAnalyticsService,
    CustomAoiStoreError,
    custom_aoi_payload,
)

BASE_URL = "https://analytics.example.com"
SQUARE = [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]]
OTHER_SQUARE = [[[2.0, 2.0], [2.0, 3.0], [3.0, 3.0], [3.0, 2.0], [2.0, 2.0]]]


def _store(response):
    requests = []

    def handle(request):
        requests.append(request)
        return response

    store = AnalyticsCustomAoiStore(
        BASE_URL, transport=httpx.MockTransport(handle)
    )
    return store, requests


class FailingStore:
    def __init__(self, error):
        self.error = error

    async def save(self, aois):
        raise self.error

    async def delete(self, aoi_id):
        raise self.error


def test_payload_combines_parts_into_one_multipolygon():
    area = CustomAreaOrm(
        id=uuid4(),
        user_id="user-1",
        name="Forest",
        geometries=[
            json.dumps({"type": "Polygon", "coordinates": SQUARE}),
            json.dumps(
                {
                    "type": "MultiPolygon",
                    "coordinates": [OTHER_SQUARE, SQUARE],
                }
            ),
        ],
    )

    assert custom_aoi_payload(area) == {
        "id": str(area.id),
        "name": "Forest",
        "user_id": "user-1",
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [SQUARE, OTHER_SQUARE, SQUARE],
        },
    }


@pytest.mark.asyncio
async def test_save_puts_aois(monkeypatch):
    monkeypatch.setenv("WRI_BEARER_TOKEN", "secret")
    store, requests = _store(httpx.Response(200, json={"status": "success"}))

    await store.save([{"id": "a"}, {"id": "b"}])

    [request] = requests
    assert request.method == "PUT"
    assert str(request.url) == BASE_URL + "/v0/custom_aois"
    assert request.headers["Authorization"] == "Bearer secret"
    assert json.loads(request.content) == {"aois": [{"id": "a"}, {"id": "b"}]}


@pytest.mark.asyncio
async def test_delete_targets_aoi():
    store, requests = _store(httpx.Response(204))

    await store.delete("abc")

    [request] = requests
    assert request.method == "DELETE"
    assert str(request.url) == BASE_URL + "/v0/custom_aois/abc"


@pytest.mark.asyncio
async def test_error_response_raises_with_status_and_detail():
    store, _ = _store(httpx.Response(422, json={"detail": "no area"}))

    with pytest.raises(CustomAoiStoreError) as raised:
        await store.save([{"id": "abc"}])

    assert raised.value.status_code == 422
    assert "no area" in raised.value.detail


@pytest.mark.asyncio
async def test_error_detail_is_truncated():
    store = AnalyticsCustomAoiStore(
        BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(422, text="x" * 50)
        ),
        max_detail_length=10,
    )

    with pytest.raises(CustomAoiStoreError) as raised:
        await store.save([{"id": "abc"}])

    assert raised.value.detail == "x" * 10


@pytest.mark.asyncio
async def test_network_error_raises_without_status():
    def fail(request):
        raise httpx.ConnectError("down")

    store = AnalyticsCustomAoiStore(
        BASE_URL, transport=httpx.MockTransport(fail)
    )

    with pytest.raises(CustomAoiStoreError) as raised:
        await store.delete("abc")

    assert raised.value.status_code is None
    assert "down" in raised.value.detail


@pytest.mark.asyncio
async def test_service_logs_failed_save():
    service = CustomAoiAnalyticsService(
        FailingStore(CustomAoiStoreError("no area", status_code=422))
    )

    with structlog.testing.capture_logs() as logs:
        await service.save([{"id": "a"}, {"id": "b"}])

    [record] = logs
    assert record["event"] == "custom_aoi_analytics_failed"
    assert record["log_level"] == "warning"
    assert record["aoi_ids"] == ["a", "b"]
    assert record["status_code"] == 422
    assert record["detail"] == "no area"


@pytest.mark.asyncio
async def test_service_logs_failed_delete():
    service = CustomAoiAnalyticsService(
        FailingStore(CustomAoiStoreError("down"))
    )
    area_id = uuid4()

    with structlog.testing.capture_logs() as logs:
        await service.delete(area_id)

    [record] = logs
    assert record["aoi_ids"] == [str(area_id)]
    assert record["status_code"] is None
