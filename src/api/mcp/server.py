"""The MCP server for Zeno's tools. The agent reaches it in-process, so its
tools act as the user of the current request."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp import Client, FastMCP
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools

from src.api.mcp import dashboards
from src.api.routers.dashboards import get_alerts_source
from src.api.services.dashboard_alerts import DashboardAlertsService


def build_server(alerts: DashboardAlertsService) -> FastMCP:
    server = FastMCP("zeno")
    dashboards.register(server, alerts)
    return server


def default_server() -> FastMCP:
    return build_server(DashboardAlertsService(get_alerts_source()))


@asynccontextmanager
async def api_tools(server: FastMCP) -> AsyncIterator[list[BaseTool]]:
    async with Client(server) as client:
        yield await load_mcp_tools(client.session)
