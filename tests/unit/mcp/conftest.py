"""Fixtures shared by the MCP tests."""

import pytest
from fastmcp.server.middleware.rate_limiting import (
    SlidingWindowRateLimitingMiddleware,
)

import src.mcp.data as data
from src.agent.datasets.handlers.base import DataPullResult
from src.mcp.server import mcp_server
from tests.unit.mcp.analytics_stub import BODY, METADATA, PARA, RESULT, StubApi


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    """Every in-process client counts as one client, "in-process", so the
    whole suite would share one minute's allowance."""
    for middleware in mcp_server.middleware:
        if isinstance(middleware, SlidingWindowRateLimitingMiddleware):
            middleware.limiters.clear()


@pytest.fixture
def api():
    stub = StubApi()
    yield stub
    stub.close()


@pytest.fixture
def replayable_pull(monkeypatch, api):
    """pull_data's area lookup and analytics handler, stubbed: the handler
    answers as the real one does, with the request it sent."""

    async def fake_lookup(aoi_ids):
        return [dict(PARA)]

    async def fake_pull(self, **kwargs):
        rows = {**RESULT, "name": ["Pará", "Pará"]}
        return DataPullResult(
            success=True,
            data=rows,
            message="ok",
            data_points_count=2,
            analytics_api_url=f"{api.url}/result/df747c81",
            analytics_api_request={
                "method": "POST",
                "url": f"{api.url}/v0/land_change/tree_cover_loss/analytics",
                "headers": {"X-environment": "production"},
                "body": BODY,
            },
            analytics_api_metadata=METADATA,
        )

    monkeypatch.setattr(data, "lookup_areas", fake_lookup)
    monkeypatch.setattr(data.AnalyticsHandler, "pull_data", fake_pull)
