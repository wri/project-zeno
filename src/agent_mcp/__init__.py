"""An experimental Zeno agent whose only tools are the MCP server's.

The tools take every input as an argument, the way the MCP tools do; none
reads agent state. A middleware projects each tool's structured result into
the state keys the frontend reads (``aoi_selection``, ``dataset``,
``charts_data`` …), under the tool names it dispatches on, so the chat UI
works unchanged. Selected with the ``mcp`` feature flag.
"""

MCP_PROFILE = "mcp"
