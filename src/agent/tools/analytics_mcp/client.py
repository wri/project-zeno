import json
from typing import Any, Callable, Protocol

from langchain_mcp_adapters.client import MultiServerMCPClient

SERVER_NAME = "analytics"


class AnalyticsMcpError(Exception):
    """A tool call the analytics MCP server rejected, with its reason."""


class AnalyticsMcp(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any]) -> Any: ...


class StreamableHttpAnalyticsMcp:
    """Calls the analytics MCP server's tools over streamable HTTP. Headers
    are read on each call, so a rotated token is picked up."""

    def __init__(self, url: str, headers: Callable[[], dict[str, str]]):
        self.url = url
        self.headers = headers

    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        client = MultiServerMCPClient(
            {
                SERVER_NAME: {
                    "transport": "streamable_http",
                    "url": self.url,
                    "headers": self.headers(),
                }
            }
        )
        async with client.session(SERVER_NAME) as session:
            result = await session.call_tool(tool, arguments)
        text = "".join(getattr(block, "text", "") for block in result.content)
        if result.isError:
            raise AnalyticsMcpError(text)
        return tool_output(result.structuredContent, text)


def tool_output(structured: Any, text: str) -> Any:
    """A tool's output. Servers wrap outputs that aren't objects, such as
    lists, under "result"."""
    if isinstance(structured, dict):
        if set(structured) == {"result"}:
            return structured["result"]
        return structured
    return json.loads(text)
