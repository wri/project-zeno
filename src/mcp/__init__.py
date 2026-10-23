"""Zeno's data tools as an open MCP server, mounted on the API at `/mcp`.

The tools call the same code the agent and the REST API call, with no
model inside: the client's own model does the reasoning. No tool needs a
user, so the server has no auth, never sees custom areas and writes nothing
to the database. See docs/mcp.md.
"""
