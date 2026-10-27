import json

import httpx
import pytest

from src.api.services.custom_aoi_store import AnalyticsCustomAoiStore

BASE_URL = "https://analytics.example.com"


def _store(batch_size=500):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"status": "success"})

    store = AnalyticsCustomAoiStore(
        BASE_URL, transport=httpx.MockTransport(handle), batch_size=batch_size
    )
    return store, requests


@pytest.mark.asyncio
async def test_save_puts_aois_in_batches(monkeypatch):
    monkeypatch.setenv("WRI_BEARER_TOKEN", "secret")
    store, requests = _store(batch_size=2)

    await store.save([{"id": str(i)} for i in range(3)])

    assert [r.method for r in requests] == ["PUT", "PUT"]
    assert str(requests[0].url) == BASE_URL + "/v0/custom_aois"
    assert requests[0].headers["Authorization"] == "Bearer secret"
    assert [
        [aoi["id"] for aoi in json.loads(r.content)["aois"]] for r in requests
    ] == [["0", "1"], ["2"]]


@pytest.mark.asyncio
async def test_delete_targets_aoi():
    store, requests = _store()

    await store.delete("abc")

    [request] = requests
    assert request.method == "DELETE"
    assert str(request.url) == BASE_URL + "/v0/custom_aois/abc"


@pytest.mark.asyncio
async def test_save_raises_on_error_response():
    store = AnalyticsCustomAoiStore(
        BASE_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(422)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await store.save([{"id": "abc"}])
