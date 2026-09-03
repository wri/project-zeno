"""Unit tests for the Langfuse fetch client (src/api/services/langfuse/fetch.py).

The traces and observations endpoints share one paging/retry implementation, so
these pin the per-endpoint parameter names (a silent rename would fetch an empty
window and zero every token column) and the paging behaviour the module docstring
promises: closed ascending windows, id-dedup, page-halving on persistent 5xx.
"""

import httpx
import pytest

from src.api.services.langfuse import fetch as F

FROM = F.datetime(2026, 9, 1, tzinfo=F.timezone.utc)
TO = F.datetime(2026, 9, 2, tzinfo=F.timezone.utc)


class _Resp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {"data": []}
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class _FakeClient:
    """Stands in for httpx.Client, recording every request it is given."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None, auth=None):
        self.calls.append((url, dict(params or {})))
        if self._responses:
            return self._responses.pop(0)
        return _Resp()


@pytest.fixture
def client():
    return F.LangfuseClient(host="http://lf", public_key="pk", secret_key="sk")


def _install(monkeypatch, responses):
    fake = _FakeClient(responses)
    monkeypatch.setattr(F.httpx, "Client", lambda **kw: fake)
    monkeypatch.setattr(F.time, "sleep", lambda *_: None)
    return fake


# --------------------------------------------------------------------------- #
# per-endpoint request shape
# --------------------------------------------------------------------------- #
def test_traces_window_uses_timestamp_bounds_ascending(monkeypatch, client):
    fake = _install(monkeypatch, [_Resp({"data": [{"id": "t1"}]})])
    assert client.fetch_window(FROM, TO) == [{"id": "t1"}]

    url, params = fake.calls[0]
    assert url == "http://lf/api/public/traces"
    assert params["fromTimestamp"].startswith("2026-09-01")
    assert params["toTimestamp"].startswith("2026-09-02")
    assert params["orderBy"] == "timestamp.asc"


def test_observations_window_uses_start_time_bounds_and_filters_generations(
    monkeypatch, client
):
    """These parameter names are load-bearing: get them wrong and the window
    comes back empty, which silently zeroes every token column."""
    fake = _install(monkeypatch, [_Resp({"data": [{"id": "o1"}]})])
    assert client.fetch_observations_window(FROM, TO) == [{"id": "o1"}]

    url, params = fake.calls[0]
    assert url == "http://lf/api/public/observations"
    assert params["fromStartTime"].startswith("2026-09-01")
    assert params["toStartTime"].startswith("2026-09-02")
    assert params["type"] == "GENERATION"


def test_observations_can_fetch_every_type(monkeypatch, client):
    fake = _install(monkeypatch, [_Resp({"data": []})])
    client.fetch_observations_window(FROM, TO, obs_type=None)
    assert "type" not in fake.calls[0][1]


def test_environment_is_forwarded_when_given(monkeypatch, client):
    fake = _install(monkeypatch, [_Resp({"data": []})])
    client.fetch_window(FROM, TO, environment="production")
    assert fake.calls[0][1]["environment"] == "production"


# --------------------------------------------------------------------------- #
# paging
# --------------------------------------------------------------------------- #
def test_pages_until_total_pages_and_dedupes_by_id(monkeypatch, client):
    fake = _install(
        monkeypatch,
        [
            _Resp(
                {"data": [{"id": "a"}, {"id": "b"}], "meta": {"totalPages": 2}}
            ),
            # "b" repeats across the page boundary; it must not be counted twice.
            _Resp(
                {"data": [{"id": "b"}, {"id": "c"}], "meta": {"totalPages": 2}}
            ),
        ],
    )
    rows = client.fetch_window(FROM, TO)
    assert [r["id"] for r in rows] == ["a", "b", "c"]
    assert [c[1]["page"] for c in fake.calls] == [1, 2]


def test_stops_on_an_empty_page(monkeypatch, client):
    _install(monkeypatch, [_Resp({"data": []})])
    assert client.fetch_observations_window(FROM, TO) == []


# --------------------------------------------------------------------------- #
# resilience
# --------------------------------------------------------------------------- #
def test_persistent_5xx_halves_the_page_size(monkeypatch, client):
    fake = _install(
        monkeypatch,
        [
            _Resp(status_code=500),
            _Resp(status_code=500),
            _Resp(status_code=500),
        ]
        + [_Resp({"data": [{"id": "a"}]})],
    )
    assert client.fetch_observations_window(FROM, TO, page_size=50) == [
        {"id": "a"}
    ]
    limits = [c[1]["limit"] for c in fake.calls]
    assert limits[0] == 50
    assert limits[-1] == 25  # window restarted at half the page size


def test_5xx_at_page_size_one_raises_rather_than_dropping_data(
    monkeypatch, client
):
    _install(monkeypatch, [_Resp(status_code=503) for _ in range(30)])
    with pytest.raises(F.LangfuseFetchError):
        client.fetch_observations_window(FROM, TO, page_size=1)
