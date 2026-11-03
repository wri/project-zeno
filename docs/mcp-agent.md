# The MCP agent (experiment)

`src/agent_mcp/` is a Zeno agent whose only tools are the MCP server's
(`src/mcp/`, see `docs/mcp.md`). It tests how the agent looks when it
consumes the MCP tools instead of importing its own. It is selected with the
`mcp` feature flag and leaves the default agent unchanged.

## How it works

- **The tools are MCP proxies.** `tools.py` lists the server's tools with a
  `fastmcp.Client` and wraps each as a LangChain tool. The model sees the
  tool's text; its structured result becomes the ToolMessage artifact. The
  server is reached in-process, or over HTTP when `ZENO_MCP_URL` is set.
- **No tool reads state.** Every input is an argument, as on the MCP server.
  The session block names the ids the tools take (`Tool ids: aoi_ids=…;
  dataset_id=…`), so the model can use an area or dataset the user picked on
  the map.
- **Tools still write state, for the frontend.** project-zeno-next
  dispatches on the tool name and reads the state keys of the same stream
  update. Three tools take the names the frontend knows, and
  `ProjectionMiddleware` writes each result into the keys it reads
  (`projections.py`):

  | Agent tool | MCP tool | State written |
  |---|---|---|
  | `pick_aoi` | `resolve_areas` | `aoi_selection`, or an `aoi_choice` nudge for candidates |
  | `pick_dataset` | `get_dataset` | `dataset`, with its map layers |
  | `pull_data` | `pull_data` | `start_date`, `end_date`, `statistics` |
  | `generate_insights` | `curated_charts` | `charts_data` (curated) |

  `search_areas`, `list_datasets` and `get_chart_code` write nothing. The
  artifact is dropped once projected, so rows and scripts are neither
  streamed nor checkpointed.

## Running it

- CLI: `uv run python src/agent/cli.py --ff mcp -q "Tree cover loss in Pará"`
  (needs the area tables in Postgres and a Gemini key).
- Frontend: open the app with `?ff=mcp` as an admin user, against a backend
  on this branch.

## Left out

Generative insights (only datasets with curated charts get a chart), saved
statistics and insights (no dashboards or "add to dashboard"), imagery,
blogs, `send_nudge`, skills, custom areas, LGMS, the dataset-alternatives
nudge, and translated tool text and chart titles (the MCP server answers in
English).

The projections import zeno code only to build the frontend's shapes: the
catalog, the date fitting, `InsightChart`, and `get_tile_services_for_dataset`
for the dataset's map layers, which `get_dataset` does not return.
