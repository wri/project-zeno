"""gnw: Global Nature Watch data on the command line.

A thin client of the GNW MCP server (`src/mcp` in project-zeno): every
command calls one of the server's tools, so the areas, the checks, the
analytics request and the curated charts stay in one place. What the CLI
adds is files: a pull lands in `gnw/pulls/<result_id>/` with its rows, its
request, its provenance and the pull.py that repeats it, so a coding agent
analyses the rows in code instead of reading them.
"""
