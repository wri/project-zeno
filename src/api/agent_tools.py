"""Selected API routes served to the agent as MCP tools, called in-process
with the caller's credentials so the routes' own auth and access rules apply."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastmcp import Client, FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools


@asynccontextmanager
async def api_tools(
    app: FastAPI, headers: dict[str, str]
) -> AsyncIterator[list[BaseTool]]:
    server = FastMCP.from_fastapi(
        app,
        route_maps=[
            RouteMap(
                methods=["GET"],
                pattern=r"^/api/dashboards$",
                mcp_type=MCPType.TOOL,
            ),
            RouteMap(
                methods=["POST"],
                pattern=r"^/api/dashboards/alerts-summary$",
                mcp_type=MCPType.TOOL,
            ),
            RouteMap(mcp_type=MCPType.EXCLUDE),
        ],
        httpx_client_kwargs={"headers": headers},
    )
    async with Client(server) as client:
        yield await load_mcp_tools(client.session)
