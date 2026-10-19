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
`source_url`, the areas, the dates and options it ran with, the `request`
sent to the analytics API, `retrieved_at`, up to 1000 rows, and `script`
(see below).

### Replaying a pull

`pull_data` and `curated_charts` return `script`: the source of a
standalone `pull.py` that replays the pull. It holds the request
`AnalyticsHandler` sent (method, URL, the `X-environment` header and the
JSON body, never the token), so it does not rebuild the request and cannot
drift from the server. It shapes the rows as `run_pull` does (area names,
the same sort order) and writes a folder:

```
gnw/pulls/<result_id>/
  rows.csv          the rows the server returned
  request.json      the request it sent
  provenance.json   the pull's provenance, with replayed_at and the
                    result id the API answered with
  pull.py           a copy of the script
```

It needs Python 3.9 or later and nothing else (`python pull.py [folder]`).
It warns when the analytics API answers with a result id other than the
one it was made from, which means the data may have changed.
`src/mcp/script.py` writes it; `tests/unit/mcp/test_script.py` runs it
against a stub API and checks that it writes the server's rows.

The script is in the structured result only. The tool's text says it is
there and does not repeat it.

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

### The charting skill

`src/mcp/skills/gnw-charting/` is an agent skill: a `SKILL.md` with the
workflow (curated charts first, then your own), rules for every chart, the
chart types GNW renders and the analyst's wording guide; one file per
dataset with its curated charts, "How to chart it", "How to present it",
cautions, options, colors and citation; and a copy of each chart generator.
The server serves it as resources (`skill://gnw-charting/SKILL.md` and the
files it links to). The same folder can be copied into a Claude or Gemini
skills folder as it is.

`src/mcp/skill.py` builds the folder from the catalog YAML, the palette, the
generators and the analyst prompts. The folder is checked in so it can be
reviewed. When you change one of its sources, rebuild it:

```sh
uv run python -m src.mcp.skill
```

`tests/unit/mcp/test_skill.py` fails while the checked-in folder is stale.

The server offers what the agent's default profile offers. LGMS is hidden:
it is hidden from the agent too, and its analytics endpoint is the only one
that needs a token.

### Views

The server gives each tool a view: an HTML page that an
[MCP Apps](https://modelcontextprotocol.io/specification/draft/extensions/apps)
host (Claude, ChatGPT) shows in place of the tool's text. The tool's
`_meta.ui.resourceUri` names its view. When the model calls the tool, the
host shows the view in a sandboxed iframe and sends it the tool's arguments
and result. The view draws the `structuredContent`.

| View | Tools | Shows |
|---|---|---|
| `ui://gnw/areas.html` | `resolve_areas`, `search_areas` | Area cards. A long selection shows as a list. The candidates of an ambiguous name and the search matches are cards: a click posts the area and its `aoi_id` to the chat. |
| `ui://gnw/datasets.html` | `list_datasets`, `get_dataset` | Dataset cards. A click calls `get_dataset` through the host and opens the details: dates, cautions, context layers, parameters, colors. |
| `ui://gnw/data.html` | `pull_data` | The rows as a table, and a quick-look chart, labelled as not a GNW chart, when the rows are over years or dates. The Reproduce panel. |
| `ui://gnw/charts.html` | `curated_charts` | One card per chart, with the curated label, a Chart / Table switch, the catalog colors, and links to the generator and the analytics result. The Reproduce panel. |
| `ui://gnw/code.html` | `get_chart_code` | The generator's source. |

The views use the look of the frontend (`project-zeno-next`): its colors,
the IBM Plex fonts, and its card and chart patterns (`InfoCard`,
`WidgetMessage`, `ChartWidget`, `formatCharts`). They draw the charts as SVG
with no chart library.

Each view is one HTML page. `src/mcp/views/__init__.py` puts the CSS and
the scripts of `src/mcp/views/` into the page, so the page loads nothing
except the fonts. Its CSP allows the font hosts only. Without the fonts, the
page uses the system fonts.

The data and chart views end with a **Reproduce** panel, closed until the
user opens it. Its tabs show `pull.py`, the request and the pull's
provenance, each with a copy button; when the host's sandbox blocks the
clipboard, the button selects the text instead. The footer gives the date
the data was retrieved. The panel is how a chat user takes a result out of
the chat and runs it again (see Replaying a pull).

A host that does not support MCP Apps does not use the views. It shows the
tool's text, as before.

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

To see the views, use Claude (claude.ai or Claude Desktop): Settings →
Connectors → Add custom connector, with the `/mcp` URL. Claude connects
from its own servers, so it cannot reach `localhost`. To test a local API,
open a temporary public URL to it, for example with a Cloudflare quick
tunnel (no account necessary):

```sh
cloudflared tunnel --url http://localhost:8000
```

The tunnel makes the full API public while it runs, not only `/mcp`. Stop
it when you finish.

## Code

| File | Holds |
|---|---|
| `src/mcp/server.py` | The FastMCP server, its instructions, the rate limit, and the app that `src/api/app.py` mounts at `/mcp` |
| `src/mcp/areas.py` | `resolve_areas`, `search_areas`, the `aoi_id` format and `lookup_areas` |
| `src/mcp/datasets.py` | `list_datasets`, `get_dataset` and the hidden datasets |
| `src/mcp/data.py` | `pull_data`, and `run_pull`, the checked pull both data tools run |
| `src/mcp/script.py` | `pull_script`, the standalone `pull.py` that replays a pull |
| `src/mcp/charts.py` | `curated_charts`, `get_chart_code` and the chart code resource |
| `src/mcp/skill.py`, `src/mcp/skills/gnw-charting/` | The charting skill and its builder |
| `src/mcp/views/` | The MCP Apps views: the shared CSS and scripts (`bridge.js` for the host protocol, `components.js`, `charts.js`, `reproduce.js` for the Reproduce panel), one script per view, and `__init__.py`, which builds and registers the pages |
| `src/agent/datasets/pull_checks.py` | The checks both `pull_data` tools run before the API call: hidden dataset, one source and the size limits for the areas (which `pick_aoi` also runs), one area for a curated-only dataset, the date range |

`tests/unit/mcp/` calls the tools through an in-process client.
`tests/unit/mcp/test_views.py` checks that each tool names a view that the
server serves, and that each page loads nothing from outside except the
fonts.
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
  `source_url`, `dataset_id`, the `aoi_ids`, the dates, `context_layer`,
  `canopy_cover`, the `request` and `retrieved_at`. These keys are a public contract. Do not rename them.
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
- Write the catalog's `code_instructions` for any charting client, not
  only zeno's code executor: some still say "REFUSE" or name the executor's
  files. The skill quotes them as they are.
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
