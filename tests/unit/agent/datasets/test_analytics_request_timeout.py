"""The analytics API can take several seconds to answer a request: for saved
custom areas it first checks that every id is saved. The handler's HTTP
clients must wait longer than that, not give up at httpx's 5 second default.
"""

import httpx
import pytest

from src.agent.datasets.handlers import analytics_handler
from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    AnalyticsHandler,
)

# The saved custom area check alone took 4.5 to 6.1 seconds on the
# production analytics API (measured 2026-11-20).
SLOWEST_ANSWER_SECONDS = 6.1


@pytest.fixture
def client_timeouts(monkeypatch):
    """The timeout of every HTTP client the handler opens."""
    timeouts = []

    class RecordingClient:
        def __init__(self, *args, **kwargs):
            timeouts.append(kwargs.get("timeout"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, headers=None, json=None):
            return httpx.Response(
                202, json={"status": "success", "data": {"link": url}}
            )

        async def get(self, url, headers=None):
            return httpx.Response(
                200, json={"data": {"status": "saved", "result": {}}}
            )

    monkeypatch.setattr(
        analytics_handler.httpx, "AsyncClient", RecordingClient
    )
    return timeouts


def _assert_outlasts_the_slowest_answer(timeouts):
    assert timeouts
    for timeout in timeouts:
        # No timeout means httpx's default of 5 seconds.
        assert timeout is not None and timeout >= SLOWEST_ANSWER_SECONDS


async def test_the_analysis_request_outlasts_the_slowest_answer(
    client_timeouts,
):
    await AnalyticsHandler()._request_analysis(
        "http://analytics/x",
        {},
        {"aoi": {"type": "admin", "ids": ["BRA"]}},
        [{"subtype": "country", "src_id": "BRA"}],
    )

    _assert_outlasts_the_slowest_answer(client_timeouts)


async def test_the_result_download_outlasts_the_slowest_answer(
    client_timeouts,
):
    await AnalyticsHandler()._process_response_data(
        {"data": {"link": "http://analytics/x/1"}},
        [],
        {"dataset_id": INTEGRATED_ALERTS_ID},
    )

    _assert_outlasts_the_slowest_answer(client_timeouts)
