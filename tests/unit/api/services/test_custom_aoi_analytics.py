import json
from uuid import uuid4

import httpx
import pytest
import structlog

from src.api.data_models import CustomAreaOrm
from src.api.services.custom_aoi_analytics import (
    CustomAoiAnalyticsService,
    custom_aoi_payload,
)

BASE_URL = "https://analytics.example.com"
SQUARE = [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]]
OTHER_SQUARE = [[[2.0, 2.0], [2.0, 3.0], [3.0, 3.0], [3.0, 2.0], [2.0, 2.0]]]


def _service(respond):
    requests = []

    def handle(request):
        requests.append(request)
        return respond(request)

    service = CustomAoiAnalyticsService(
        BASE_URL, transport=httpx.MockTransport(handle)
    )
    return service, requests


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
    service, requests = _service(lambda request: httpx.Response(200))

    with structlog.testing.capture_logs() as logs:
        await service.save([{"id": "a"}, {"id": "b"}])

    [request] = requests
    assert request.method == "PUT"
    assert str(request.url) == BASE_URL + "/v0/custom_aois"
    assert request.headers["Authorization"] == "Bearer secret"
    assert json.loads(request.content) == {"aois": [{"id": "a"}, {"id": "b"}]}
    assert logs == []


@pytest.mark.asyncio
async def test_error_response_is_logged():
    service, _ = _service(
        lambda request: httpx.Response(422, json={"detail": "no area"})
    )

    with structlog.testing.capture_logs() as logs:
        await service.save([{"id": "a"}, {"id": "b"}])

    [record] = logs
    assert record["event"] == "custom_aoi_analytics_failed"
    assert record["log_level"] == "warning"
    assert record["aoi_ids"] == ["a", "b"]
    assert record["status_code"] == 422
    assert "no area" in record["detail"]


@pytest.mark.asyncio
async def test_network_error_on_delete_is_logged():
    def fail(request):
        raise httpx.ConnectError("down")

    service, requests = _service(fail)
    area_id = uuid4()

    with structlog.testing.capture_logs() as logs:
        await service.delete(area_id)

    [request] = requests
    assert request.method == "DELETE"
    assert str(request.url) == f"{BASE_URL}/v0/custom_aois/{area_id}"
    [record] = logs
    assert record["aoi_ids"] == [str(area_id)]
    assert record["status_code"] is None
    assert "down" in record["detail"]
