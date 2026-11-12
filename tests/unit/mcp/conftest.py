"""Fixtures shared by the MCP tests."""

import pytest
from fastmcp.server.middleware.rate_limiting import (
    SlidingWindowRateLimitingMiddleware,
)

from src.mcp.server import mcp_server


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    """Every in-process client counts as one client, "in-process", so the
    whole suite would share one minute's allowance."""
    for middleware in mcp_server.middleware:
        if isinstance(middleware, SlidingWindowRateLimitingMiddleware):
            middleware.limiters.clear()
