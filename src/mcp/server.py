"""The FastMCP server and the ASGI app the API mounts at `/mcp`.

Stateless streamable HTTP: every request stands alone, so any API replica
serves any call. There is no auth; a per-client rate limit bounds what one
caller can send through to the analytics API.
"""

import os

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware.middleware import MiddlewareContext
from fastmcp.server.middleware.rate_limiting import (
    SlidingWindowRateLimitingMiddleware,
)

from mcp.types import ToolAnnotations
from src.mcp.areas import resolve_areas, search_areas
from src.mcp.data import pull_data
from src.mcp.datasets import get_dataset, list_datasets
from src.shared.version import get_version

INSTRUCTIONS = """\
Global Nature Watch data: forest, land cover, land use and nature datasets \
for countries, administrative areas, protected areas, key biodiversity areas \
and indigenous lands.

To answer a question with data:
1. resolve_areas with the places the user names, and the subregion when \
they compare the parts of a place. When it returns candidates, ask the user \
which one they mean. Use the aoi_ids it returns; never write an area id from \
memory. search_areas lists matches for a name when you need to browse.
2. list_datasets, then get_dataset for the one that measures what the user \
asks about. It lists the dataset's context layers, parameters and cautions.
3. pull_data with the area ids and the dataset id.

Quote only numbers a tool returned, mention the dataset's cautions where \
they matter, and give its citation. Custom (user-drawn) areas are not \
available here."""

# Requests per client per minute.
RATE_LIMIT_PER_MINUTE = int(os.getenv("MCP_RATE_LIMIT_PER_MINUTE", "120"))
# The proxies in front of the API that append to X-Forwarded-For: one, the
# ingress (or the ALB of an ephemeral deploy). A client writes whatever it
# likes into the header, and each proxy appends the address it saw, so only
# the entry the outermost of our proxies appended names the client. 0 trusts
# no header and uses the peer address.
TRUSTED_PROXY_HOPS = int(os.getenv("MCP_TRUSTED_PROXY_HOPS", "1"))

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def _client_id(context: MiddlewareContext) -> str:
    try:
        request = get_http_request()
    except RuntimeError:
        # In-process clients (tests) have no HTTP request.
        return "in-process"
    return client_address(
        request.headers.get("x-forwarded-for", ""),
        request.client.host if request.client else "unknown",
    )


def client_address(
    forwarded: str, peer: str, hops: int = TRUSTED_PROXY_HOPS
) -> str:
    """The rate-limit key: the X-Forwarded-For entry `hops` from the right,
    the last one a client cannot write itself; the peer address when the
    header is shorter or not trusted."""
    entries = [entry.strip() for entry in forwarded.split(",")]
    entries = [entry for entry in entries if entry]
    if hops > 0 and len(entries) >= hops:
        return entries[-hops]
    return peer


def build_server() -> FastMCP:
    server = FastMCP(
        name="Global Nature Watch",
        instructions=INSTRUCTIONS,
        version=get_version(),
        # An unexpected exception reaches the client as its type only; a
        # ToolError's message, written for the model, passes through.
        mask_error_details=True,
        middleware=[
            SlidingWindowRateLimitingMiddleware(
                max_requests=RATE_LIMIT_PER_MINUTE,
                window_minutes=1,
                get_client_id=_client_id,
            )
        ],
    )
    for tool in (
        resolve_areas,
        search_areas,
        list_datasets,
        get_dataset,
        pull_data,
    ):
        server.tool(tool, annotations=_READ_ONLY)
    return server


mcp_server = build_server()


def build_app():
    """The ASGI app for `/mcp`. Its lifespan must run inside the API's."""
    return mcp_server.http_app(path="/", stateless_http=True)


class ExactMountPath:
    """Serve a mount's bare path (`/mcp`) without the `/mcp/` redirect.

    Starlette answers `/mcp` with a 307 to `/mcp/`. MCP clients POST to the
    URL they were given and not every one follows the redirect, and behind
    a TLS-terminating proxy the redirect can point at plain http.
    """

    def __init__(self, app, path: str):
        self.app = app
        self.path = path.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == self.path:
            scope = {**scope, "path": self.path + "/"}
        await self.app(scope, receive, send)
