# The MCP server

The API serves Zeno's data tools as an open [MCP](https://modelcontextprotocol.io)
server at `/mcp`. Any MCP client (Gemini CLI, Claude, an agent of your own)
can find areas, read the dataset catalog and pull statistics with the code
the agent and the REST API use. The code is in `src/mcp/`.

The tools have **no model inside**. The client's own model does the
reasoning: it reads the area candidates and the dataset descriptions and
chooses. That keeps the server cheap to run and its answers deterministic.

## What it offers

| Tool | Does | Calls |
|---|---|---|
| `resolve_areas(places, subregion?, admin_term?)` | Resolves the places a user names to areas, the way the agent's geocoder does: picks the best match for each place, expands subregions ("the districts of Odisha"), and returns candidates instead of a pick when a name is a prominent place in more than one country. | `Geocoder.lookup`, the deterministic half of `pick_aoi`. The calling model fills in the `places` fields (`ExtractedPlace`) that the geocoder's Flash step extracts in the agent. |
| `search_areas(name, sources?, limit?)` | Finds countries, administrative areas, protected areas, key biodiversity areas and indigenous lands by name. Returns each match with an `aoi_id`. | `search_aois`, the search behind `GET /api/aois` and the agent's `pick_aoi` |
| `list_datasets()` | Lists the datasets with a short description of each. | the catalog YAML (`selection_card`) |
| `get_dataset(dataset_id)` | One dataset's description, dates, context layers, parameters, cautions, charting and presentation guidance, colors and citation. | the catalog YAML and `palette.py` |
| `pull_data(aoi_ids, dataset_id, start_date?, end_date?, context_layer?, canopy_cover?, change_over_time?)` | Pulls the statistics from the GNW analytics API and returns the rows. | `pull_checks` and `AnalyticsHandler`, as the agent's `pull_data` does |

An area id is `<source>:<src_id>`, for example `gadm:BRA.14_1`. It is the
same pair that the REST API's `AreaOfInterest` and the agent's
`aoi_selection` hold, in one string a model can copy.

One pull takes areas from one source, at most 1000 administrative areas or
50 of any other kind: the limits `pick_aoi` applies to a selection, checked
for every pull by `refuse_areas` in `pull_checks`.

`pull_data` returns the rows in its text: as CSV when there are at most 200
rows and the CSV fits in 7,000 characters (`TEXT_CHAR_BUDGET`, about 2,000
tokens), as per-column stats otherwise, with a line saying where all the rows
are. The budget counts characters, not tokens, because the client's model,
and so its tokenizer, is not known. Numbers in the text are rounded to two
decimals (four significant digits below 1); the structured rows keep full
precision. A model that gets a handle without the numbers invents them, so
a small result always comes with its numbers. The structured result adds
the analytics `result_id` and `source_url`, the areas, the dates and options
it ran with, and up to 1000 rows.

## Design choices

- **No auth.** Every tool reads public data, so the server needs no user.
  Custom areas belong to a user, so the server never sees them:
  `search_aois(include_custom=False)` leaves them out, and a `custom:` id is
  refused before any query.
- **Nothing is saved.** The server writes no statistics, insights or threads.
  The analytics API keeps each result, under an id it makes from the
  request. The `result_id` is therefore a stable handle, and anyone can
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
| `src/mcp/data.py` | `pull_data`, and `run_pull`, the checked pull it runs |
| `src/agent/datasets/pull_checks.py` | The checks both `pull_data` tools run before the API call: hidden dataset, one source and the size limits for the areas (which `pick_aoi` also runs), one area for a curated-only dataset, the date range |

`tests/unit/mcp/` calls the tools through an in-process client.

## Next steps

- **Curated charts**: GNW's own charts for a pull, and the code that draws
  them (`curated_charts`, `get_chart_code`).
- **Provenance and repeatability**: the request sent to the analytics API,
  a digest of the rows and a standalone `pull.py` that replays a pull.
- **Views** for MCP Apps hosts, a charting skill, and a `gnw` CLI for
  coding agents.
- **Auth**, to reach custom areas and to save insights.
