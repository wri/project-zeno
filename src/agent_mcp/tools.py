"""The MCP server's tools as LangChain tools, under the names the frontend
dispatches on.

Each tool is a thin proxy: it sends its arguments to the MCP tool and
returns the tool's text for the model and its structured result as the
ToolMessage artifact, which ``ProjectionMiddleware`` turns into state.

The server is reached in-process by default; set ``ZENO_MCP_URL`` (e.g.
``http://localhost:8000/mcp``) to go through HTTP instead.
"""

import copy
import os
import re
from typing import Any, Optional

from fastmcp import Client
from langchain_core.tools import StructuredTool, ToolException

# MCP tool name -> the name the agent and the frontend use. The other tools
# keep their MCP names.
RENAMES = {
    "resolve_areas": "pick_aoi",
    "get_dataset": "pick_dataset",
    "curated_charts": "generate_insights",
}

# pick_dataset selects the dataset for the map, so it takes the options the
# map layer is drawn with as well. They are copied from pull_data's schema
# and not sent to get_dataset, which takes only the dataset id.
_PICK_DATASET_OPTIONS = (
    "context_layer",
    "canopy_cover",
    "start_date",
    "end_date",
)

_EXTRA_DESCRIPTION = {
    "pick_aoi": (
        "Puts the selected areas on the user's map. Call it again when the "
        "user names other places."
    ),
    "pick_dataset": (
        "This selects the dataset: it puts its layer on the user's map. "
        "Call it once you know the dataset, with the context_layer, "
        "canopy_cover and dates you will pull with."
    ),
    "generate_insights": (
        "Shows the charts in the user's insight panel. Only datasets marked "
        "'curated charts' in list_datasets have them."
    ),
}

_RENAME_PATTERN = re.compile(r"\b(" + "|".join(RENAMES) + r")\b")


def rename(text: str) -> str:
    """Text from the server with its tool names replaced by the agent's."""
    return _RENAME_PATTERN.sub(lambda m: RENAMES[m.group(1)], text)


def mcp_target() -> Any:
    """What a fastmcp Client connects to: the URL in ``ZENO_MCP_URL``, or
    the server object itself (in-process)."""
    url = os.getenv("ZENO_MCP_URL")
    if url:
        return url
    from src.mcp.server import mcp_server

    return mcp_server


def _schema(name: str, schema: dict, schemas: dict[str, dict]) -> dict:
    schema = copy.deepcopy(schema)
    if name == "get_dataset":
        options = schemas["pull_data"]["properties"]
        for key in _PICK_DATASET_OPTIONS:
            schema["properties"][key] = copy.deepcopy(options[key])
        schema["properties"]["reason"] = {
            "type": "string",
            "description": "One sentence on why this dataset answers the "
            "question; shown to the user.",
        }
    return schema


def _proxy(mcp_name: str, target: Any, forward: Optional[set[str]]):
    async def call(**kwargs) -> tuple[str, dict]:
        args = {
            key: value
            for key, value in kwargs.items()
            if value is not None and (forward is None or key in forward)
        }
        async with Client(target) as client:
            result = await client.call_tool(
                mcp_name, args, raise_on_error=False
            )
        text = rename(
            "\n".join(
                block.text
                for block in result.content
                if getattr(block, "text", None)
            )
        )
        if result.is_error:
            raise ToolException(text or f"{mcp_name} failed.")
        return text, result.structured_content or {}

    return call


async def mcp_tools(target: Any = None) -> list[StructuredTool]:
    """One LangChain tool per MCP tool, and the server's instructions."""
    target = target if target is not None else mcp_target()
    async with Client(target) as client:
        listed = await client.list_tools()
    schemas = {tool.name: tool.input_schema for tool in listed}

    tools = []
    for tool in listed:
        name = RENAMES.get(tool.name, tool.name)
        description = rename(tool.description or "")
        if name in _EXTRA_DESCRIPTION:
            description += "\n\n" + _EXTRA_DESCRIPTION[name]
        forward = (
            set(tool.input_schema.get("properties", {}))
            if tool.name == "get_dataset"
            else None
        )
        tools.append(
            StructuredTool(
                name=name,
                description=description,
                args_schema=_schema(tool.name, tool.input_schema, schemas),
                coroutine=_proxy(tool.name, target, forward),
                response_format="content_and_artifact",
                handle_tool_error=True,
            )
        )
    return tools


async def mcp_instructions(target: Any = None) -> str:
    """The server's instructions, with the agent's tool names."""
    target = target if target is not None else mcp_target()
    async with Client(target) as client:
        instructions = client.instructions or ""
    return rename(instructions)
