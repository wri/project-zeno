# The MCP server

The API serves Zeno's data tools as an open [MCP](https://modelcontextprotocol.io)
server at `/mcp`. Any MCP client (Gemini CLI, Claude, an agent of your own)
can find areas, read the dataset catalog, pull statistics and get GNW's own
charts with the code the agent and the REST API use. The code is in `src/mcp/`.

The tools have **no model inside**. The client's own model does the
reasoning: it reads the area candidates and the dataset descriptions and
chooses. That keeps the server cheap to run and its answers deterministic.

## What it offers

| Tool | Does | Calls |
|---|---|---|
| `resolve_areas(places, subregion?, admin_term?)` | Resolves the places a user names to areas, the way the agent's geocoder does: picks the best match for each place, expands subregions ("the districts of Odisha"), and returns candidates instead of a pick when a name is a prominent place in more than one country. | `Geocoder.lookup`, the deterministic half of `pick_aoi`. The calling model fills in the `places` fields (`ExtractedPlace`) that the geocoder's Flash step extracts in the agent. |
| `search_areas(name, sources?, limit?)` | Finds countries, administrative areas, protected areas, key biodiversity areas and indigenous lands by name. Returns each match with an `aoi_id`. | `search_aois`, the search behind `GET /api/aois` and the agent's `pick_aoi` |
| `list_datasets()` | Lists the datasets with a short description of each, and marks those with curated charts. | the catalog YAML (`selection_card`) |
| `get_dataset(dataset_id)` | One dataset's description, dates, context layers, parameters, cautions, charting and presentation guidance, colors and citation. | the catalog YAML and `palette.py` |
| `pull_data(aoi_ids, dataset_id, start_date?, end_date?, context_layer?, canopy_cover?, change_over_time?)` | Pulls the statistics from the GNW analytics API and returns the rows. | `pull_checks` and `AnalyticsHandler`, as the agent's `pull_data` does |
| `curated_charts(…the pull_data arguments)` | Pulls the data and returns the charts GNW itself shows for the dataset: chart specs with their rows and colors, the pull's provenance and the generator that drew them. | the pull of `pull_data`, then `build_curated_charts`, as `/api/analyze` and the agent's `generate_insights` do |
| `get_chart_code(dataset_id)` | The source of the dataset's chart generator, also served as the resource `gnw://charts/{dataset_id}/code`. | the modules in `src/api/services/charts` |

An area id is `<source>:<src_id>`, for example `gadm:BRA.14_1`. It is the
same pair that the REST API's `AreaOfInterest` and the agent's
`aoi_selection` hold, in one string a model can copy.

One pull takes areas from one source, at most 1000 administrative areas or
50 of any other kind: the limits `pick_aoi` applies to a selection, checked
for every pull by `refuse_areas` in `pull_checks`.

`pull_data` returns the rows in its text, as CSV up to 200 rows and as
per-column stats beyond that. A model that gets a handle without the numbers
invents them. The structured result adds the analytics `result_id` and
`source_url`, the areas, the dates and options it ran with, and up to 1000
rows.

### Curated charts

`curated_charts` gives a client the trusted view of a dataset: the charts
GNW draws itself, from code GNW maintains and reviews, rather than charts
the client's model writes. Each chart is an `InsightChart` (`chart_type`,
`x_axis`, `y_axis`, `color_field`, `series_fields`, `chart_data`,
`color_map`, `series_color`, …), the shape the frontend renders and
`InsightOrm` stores. The result carries the pull's provenance (the same keys
as `pull_data`), `curated: true`, and the generator's name, path and
GitHub link.

The shared builder leaves curated colors to the frontend, so the MCP tool
fills them in from the catalog palette: the series color, and a color for
each category, matched by slug or by English label (the analytics API
returns "Settlements and infrastructure" where the catalog says
"Settlements & Infrastructure"). A color a generator sets itself stays.

`get_chart_code` returns the generator's source, so a model can explain a
curated chart or follow the same choices (which rows to keep, how to sort and
sum them, which chart type) when it draws its own.

The server offers what the agent's default profile offers. LGMS is hidden:
it is hidden from the agent too, and its analytics endpoint is the only one
that needs a token.

## Design choices

- **No auth.** Every tool reads public data, so the server needs no user.
  Custom areas belong to a user, so the server never sees them:
  `search_aois(include_custom=False)` leaves them out, and a `custom:` id is
  refused before any query.
- **Nothing is saved.** The server writes no statistics, insights or threads.
  The analytics API keeps each result, under an id that is the same for the
  same request. The `result_id` is therefore a stable handle, and anyone can
  fetch it from `source_url` without a token.
- **The analytics token is optional.** When `WRI_BEARER_TOKEN` is set, the
  server sends it, as the agent does. When it is not set, the requests go
  without an `Authorization` header. The client never sends a token.
- **Rate limit.** Each client may send `MCP_RATE_LIMIT_PER_MINUTE` requests
  a minute (default 120). The limit counts in each API process. A client is
  the `X-Forwarded-For` entry that the outermost of our proxies appended,
  `MCP_TRUSTED_PROXY_HOPS` from the right (default 1: the ingress). Entries
  further left are written by the client and are never used.
- **Stateless HTTP.** Each request stands alone, so any API replica serves
  any call. `/mcp` and `/mcp/` both answer, without a redirect.
- **Errors are written for the model.** A refused call (an unknown id, a
  context layer the dataset does not have, dates outside its coverage) says
  what is wrong and where to get a valid value. An unexpected exception
  reaches the client as its type only.

## Connect a client

Locally, with `make api` running:

```json
// Gemini CLI: ~/.gemini/settings.json
{
  "mcpServers": {
    "gnw": { "httpUrl": "http://localhost:8000/mcp" }
  }
}
```

Use the deployed API's URL the same way. To look at the tools without a
model, run `npx @modelcontextprotocol/inspector` and connect it to the same
URL.

## Code

| File | Holds |
|---|---|
| `src/mcp/server.py` | The FastMCP server, its instructions, the rate limit, and the app that `src/api/app.py` mounts at `/mcp` |
| `src/mcp/areas.py` | `resolve_areas`, `search_areas`, the `aoi_id` format and `lookup_areas` |
| `src/mcp/datasets.py` | `list_datasets`, `get_dataset` and the hidden datasets |
| `src/mcp/data.py` | `pull_data`, and `run_pull`, the checked pull both data tools run |
| `src/mcp/charts.py` | `curated_charts`, `get_chart_code` and the chart code resource |
| `src/agent/datasets/pull_checks.py` | The checks both `pull_data` tools run before the API call: hidden dataset, one source and the size limits for the areas (which `pick_aoi` also runs), one area for a curated-only dataset, the date range |

`tests/unit/mcp/` calls the tools through an in-process client.
`tests/unit/agent/datasets/test_analytics_request_snapshot.py` pins the exact
request the analytics handler sends for every dataset, option and area type.
That test protects all three callers of the handler.

## Next steps

### Insights the client makes, posted back

Today a client draws its own charts from the rows, or takes GNW's curated
charts. Next, it should be able to post the insight it made, so that the
insight can be saved, shared and shown in GNW like the agent's insights. The design keeps this possible now:

- **A pull is its own provenance.** The structured result of `pull_data`
  holds everything a saved insight needs to name its source: `result_id`,
  `source_url`, `dataset_id`, the `aoi_ids`, the dates, `context_layer` and
  `canopy_cover`. These keys are a public contract. Do not rename them.
- **Charts in the shape GNW renders.** A posted insight should carry its
  charts in the `InsightChart` shape (`chart_type`, `x_axis`, `y_axis`,
  `series_fields`, `chart_data`, …) that `InsightOrm` stores and the
  frontend renders. Then the insight needs no new chart model, and a
  curated chart from `curated_charts` can be posted as it is.
- **A route, not a database write from the MCP server.** For example
  `POST /api/insights` takes `{title, text, charts, sources: [pull
  provenance]}`. The MCP server can expose it as a `save_insight` tool. The
  write needs an owner, so it comes with auth (below).
- **Verification.** Because each source names its `source_url`, the API can
  fetch the rows again and check the chart data against them before it marks
  an insight as GNW data, rather than trusting what the client sent.

### More tools

- `get_statistics(result_id)`: page through results larger than the 1000 rows
  `pull_data` returns.
- A charting skill built from the catalog guidance (`code_instructions`,
  `presentation_instructions`, the palette) and the curated generators, one
  section per dataset, served over MCP (FastMCP can serve skills as
  resources).
- Curated colors in `build_curated_charts` itself, so that the REST API and
  the agent send them too, and the MCP tool's own color step goes away.

### Later

- **Auth**, to reach custom areas and to save insights. The easy step is an
  optional bearer token (an RW token or a machine key, checked by the
  existing `fetch_user_from_rw_api`). A full login is harder: RW publishes no
  OAuth discovery for MCP clients to use.
- **Evals** with Gemini as the client model, on the `gnw-gold-evals` sets.
- **Zeno's own agent** using these tools instead of its in-process versions.
- Check upstream whether protected-area pulls work. They failed at the
  analytics API in August, in the `project-zeno-mcp` port.
