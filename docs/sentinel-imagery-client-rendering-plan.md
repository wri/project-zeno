# Plan: render Sentinel-2 imagery in the browser

Status (2026-11-25):

- Phase 1 (frontend) is on project-zeno-next branch
  `feat/client-sentinel2-imagery`.
- Phase 2 (agent, dashboards) is on project-zeno branch
  `feat/client-imagery-agent`, plus a follow-up commit on the frontend
  branch. Deploy the frontend first: it must understand `render: "client"`
  payloads before the backend sends them.
- Not done yet: running `migrate-imagery-widgets --apply` in each
  environment, then removing the mosaic service, the `/mosaic` router, the
  `MOSAIC_S3_*` settings, `cogeo_mosaic`/`pystac_client`, and the
  frontend flag (see "Removal" below).

Phase 2 as built:

- `show_imagery` (and the Planet fallback, and the analysis-template
  imagery widget) write `render: "client"` and the recipe token as
  `mosaic_id`, with no geometry lookup, STAC search or S3 write. The token
  moved to `src/shared/imagery_recipe.py`.
- The frontend sends `view_context.visible_imagery` (scene count, dates or
  status). The session line shows it as `Imagery: ... (map: ...)` and
  `inspect_view_context` lists it.
- Dashboard map widgets accept `render: "client"` imagery (no `tile_url`)
  and render it in the browser; the export waits for the scenes to draw.
- `python src/api/cli.py migrate-imagery-widgets [--apply]` rewrites saved
  Sentinel-2 widgets from S3 mosaics to the client form.

Differences from this plan in the phase 1 code:

- Feature flag: the existing URL flag mechanism, `?ff=client-imagery`, not
  an environment variable.
- Layer order: an empty MapLibre anchor layer (`client-imagery-sentinel`)
  under all rasters, not a computed `beforeId`. A fixed anchor never
  disappears while deck.gl uses it.
- Scene limits: 2 scenes per MGRS tile, 24 in total, minimum zoom 8.
- Date control: a native date input, not `DatePicker` (that component is
  range-only and opens its own popover).
- Earliest date: 2016-11-01, the oldest item in earth-search (the
  collection extent says 2015-06-27, but no item is older).
- Code: `src/features/imagery` (model, lib, api, ui),
  `app/store/sentinel2Captures.ts`, `ClientImageryLayers.tsx`, and changes
  to `showImagery.ts`, the imagery legend and `viewContext.ts`
  (`visible_imagery`).

## Goal

Remove the server-side Sentinel-2 mosaic. The frontend searches the STAC API
and renders the Cloud-Optimized GeoTIFFs (COGs) directly, with the same
technology that [stac-map](https://github.com/developmentseed/stac-map) uses.
Later, the agent only sets the imagery parameters on the UI.

Scope of this plan:

- **Phase 1 (now): frontend only.** The backend does not change.
- **Phase 2 (later): agent tool and cleanup.** The frontend design in
  phase 1 must make phase 2 a small change. Section "Phase 2" gives the
  contract.

Planet imagery is out of scope. Planet serves XYZ basemap tiles, not COGs, so
`show_planet_imagery` does not change.

## Current flow

1. The agent calls `show_imagery` (`src/agent/tools/show_imagery.py`).
2. `create_sentinel2_mosaic` (`src/api/services/mosaic.py`) loads the AOI
   geometry, rejects AOIs > 50,000 km², searches earth-search
   (`sentinel-2-l2a`, ±window days, cloud < N %, max 50 items), sorts the
   items by distance from the target date, builds a MosaicJSON and writes it
   to S3.
3. The tool writes `ImageryState` to agent state: a GFW-tiler `tile_url`,
   a `tilejson_url`, scene statistics and the recipe values.
4. `app/store/chat-tools/showImagery.ts` gets the TileJSON and adds a
   MapLibre raster layer (`DynamicTileLayers.tsx`).

## What stac-map does

- `MosaicLayer` and `COGLayer` from `@developmentseed/deck.gl-geotiff`
  render a list of STAC items. Each COG is read with HTTP range requests
  (`@developmentseed/geotiff`, `@chunkd/*`) and drawn on the GPU.
  `epsgResolver` from `@developmentseed/proj` reprojects UTM scenes to Web
  Mercator. There is no tiler and no server.
- `PageLayer` in `src/components/visualization.tsx` gives each item's COG
  href to `MosaicLayer`. The layer opens a GeoTIFF only for items in the
  viewport (`getSource`) and makes one `COGLayer` for each item
  (`renderSource`).
- `loadGeoTIFF` in `src/utils/geotiff.ts` sends a HEAD request first. This
  is a workaround for a `@chunkd/source-http` bug (stac-map issue 459). We
  must copy it.
- `src/components/map.tsx` adds deck.gl to `react-map-gl/maplibre` with
  `MapboxOverlay` from `@deck.gl/mapbox`.
- The STAC search is a plain `fetch`. No STAC client library.

Our frontend uses `maplibre-gl` 6 and `react-map-gl` 8, the same as stac-map.
It does not use deck.gl yet. It builds with Vite and prerenders pages with
SSR (`vite build --ssr` + `scripts/prerender.mjs`), so the deck.gl code must
load only in the browser.

## Phase 1 design (frontend)

### Core idea: one request type, three inputs

All imagery code takes one type. Nothing below this type knows where the
request came from.

```ts
interface Sentinel2Request {
  aois: { source: string; srcId: string; name: string }[];
  targetDate: string;      // YYYY-MM-DD
  windowDays: number;      // 1..183
  maxCloudCover: number;   // 1..100
  maxScenes?: number;      // default from config, see "Limits"
}
```

The request comes from one of three adapters:

1. **Current agent payload (phase 1).** The existing `show_imagery`
   payload already has `target_date`, `window_days`, `max_cloud_cover` and
   `aoi_names`. Its `mosaic_id` is the recipe token from `encode_recipe`:
   base64url JSON with `a` (AOI source and src_id pairs), `d`, `w`, `c`,
   `n`. The adapter decodes `mosaic_id` to get the exact AOI refs. The
   adapter ignores `tile_url`. The backend still builds the S3 mosaic in
   phase 1, but the frontend does not use it.
2. **UI controls (phase 1).** The imagery legend entry gets controls for
   date, window and cloud limit. A change makes a new request for the same
   AOIs. The user can then fix "no scenes" without the agent.
3. **Future agent payload (phase 2).** A payload with `render: "client"`
   and the recipe fields in plain form. The adapter maps the fields and
   does no decoding.

Layer identity: `imageryId = hash(request)`, deterministic. The same request
upserts the same layer, so a thread replay does not add layers. For adapter
1, use `mosaic_id` as the id, so the ids match the current ones.

### Module layout

New feature folder `src/features/imagery/sentinel2/`:

| File | Content |
| --- | --- |
| `request.ts` | `Sentinel2Request`, defaults, clamping, `imageryId`, the three adapters |
| `search.ts` | STAC search, sort, limits, statistics. Pure functions plus `fetch`; no React |
| `useSentinel2Scenes.ts` | TanStack Query hook: request + geometry → scenes and status |
| `geotiff.ts` | `loadGeoTIFF`, copied from stac-map with its comment |
| `Sentinel2Layers.tsx` | deck.gl layers for all client imagery layers; lazy-loaded |
| `__tests__/` | unit tests for the adapters, sort, limits and statistics |

### STAC search (`search.ts`)

- `POST https://earth-search.aws.element84.com/v1/search` with
  `collections: ["sentinel-2-l2a"]`, `intersects` = convex hull of the AOI
  union (same reason as `search_geometry` in `mosaic.py`: Elasticsearch
  rejects some rings), `datetime` = target date ± window with the end
  clamped to today, `query: {"eo:cloud_cover": {"lt": N}}`. Follow `next`
  links until the search limit.
- AOI geometry: get it from the layer store registry (the `pick_aoi`
  handler adds it). If it is not there, use
  `GET /api/geometry/{source}/{src_id}`.
- Sort the items: distance from the target date, then cloud cover. This is
  the backend order.
- Apply the limits (next section), then compute the legend statistics:
  `itemCount`, `startDate`, `endDate`, `meanCloudCover`.
- Result status: `ok`, `no_scenes`, `too_large`, `error`.

### Limits

Speed depends on the number of COGs that the browser opens. We limit this in
three places:

1. **Maximum AOI area.** Compute the area with `@turf/area` (already a
   dependency). Above the limit (start with 50,000 km², the backend value),
   do not search. Show status `too_large`.
2. **Maximum scenes per footprint, then maximum scenes in total.** Sentinel-2
   scenes come in fixed 110 × 110 km MGRS tiles (property
   `grid:code`, for example `MGRS-20LNP`). A plain cap on the total can drop a whole
   tile and leave a hole in the AOI. So, after the sort, keep the best
   `maxScenesPerTile` items for each MGRS tile (start with 3). Then cap the
   total at `maxScenes` (start with 40). With 50,000 km² this is about
   6 to 10 tiles, so the caps seldom drop coverage.
3. **Minimum zoom.** Do not render below zoom 8, as now.
   `ImageryZoomHint` already tells the user to zoom in. `MosaicLayer` opens
   only the COGs in the viewport, so the cost at zoom 8 and higher is low.

Put the three values in one config object, so we can tune them after the
spike and the agent can later send `maxScenes`.

### Rendering (`Sentinel2Layers.tsx`)

- Add the dependencies at the versions in stac-map `package.json`:
  `@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/mapbox`,
  `@developmentseed/deck.gl-geotiff`, `@developmentseed/geotiff`,
  `@developmentseed/proj`, `@chunkd/source`, `@chunkd/source-http`,
  `@chunkd/middleware`, `@turf/convex`.
- Add one `MapboxOverlay` with `interleaved: true` to `app/components/Map.tsx`.
  Interleaved mode lets a deck.gl layer take a MapLibre `beforeId`. Put the
  imagery below the dataset rasters, the same order that
  `DynamicTileLayers` uses now.
- For each visible layer with client imagery, make one `MosaicLayer`:
  `sources` = the limited items, `getSource` = `loadGeoTIFF(visual href)`,
  `renderSource` = `COGLayer` with `epsgResolver`. Use the `visual` asset
  (8-bit true colour, nodata 0), as the backend does. No band pipeline is
  necessary.
- Opacity and visibility come from the layer manager.
- Load this module with `React.lazy` inside a client-only boundary, so SSR
  prerendering does not import deck.gl or WASM.

### Store and legend changes

- `Layer` in `app/store/layerManagerSlice.ts`: add
  `sentinel2?: { request: Sentinel2Request }`. Such a layer has no
  `tileUrl`, so `DynamicTileLayers` skips it.
- `showImagery.ts`: for a Sentinel-2 payload with the feature flag on, use
  adapter 1 and add a client layer. Do not get the TileJSON. Planet and the
  flag-off path do not change.
- Legend (`buildImageryGroup`, `toImageryMeta`): read the statistics from
  the search result, not from the payload. Show the status as the capture
  note ("No scenes found. Try a wider window or a higher cloud limit.").
- Thumbnail: `imageryThumbnailUrl` needs a tile URL. Use the `thumbnail`
  asset of the first sorted item.
- Report the result in `view_context.visible_layers` (`imagery_id`,
  status, scene count, dates). `ViewContext` has `extra="allow"`, so the
  backend accepts it now. The agent can use it in phase 2.

### Imagery filters in the legend

Source: the legend design (Satellite Imagery entry with an **Edit** link
after the parameter chips). Most of that design is already in
`app/components/legend/ImageryLegendEntry.tsx`: header, thumbnail, chips,
captures grouped by area, LIVE badge, visibility switches. The new parts are
the **Edit** link and the filter controls. The dataset entry in the same
design also has **Edit**; there is no parameter-edit pattern in the
frontend yet.

Decision: the filters go into the legend as a popover. They do not need a
separate module. Three controls fit in a popover of about 290 px, and the
legend does not grow. `OpacityControl` already uses this pattern
(Chakra `Popover`).

**Trigger.** An **Edit** text link after the chips (DATES, WINDOW, CLOUD).
The AREA chip stays read-only: the area comes from the AOI selection.

**Popover content:**

| Control | Type | Values | Default |
| --- | --- | --- | --- |
| Date | `DatePicker` (`app/components/DatePicker.tsx`) and a **Latest** button | 2017-03-28 (first L2A scene on earth-search; check) to today | target date of the live capture |
| Window | segmented buttons | ±7, ±15, ±30, ±60 days | live capture value |
| Max cloud cover | segmented buttons | 10, 20, 30, 50, 80 % | live capture value |

Segmented buttons, not sliders: the values map to the agent tool
arguments, they are fast to compare between captures, and the chips show
the same values.

**Preview line.** While the user changes a value, run the STAC search
(debounce 400 ms, TanStack Query, same cache as the layer). Show "9 scenes
in range", "24+ scenes, the best 24 are shown" (limit hit) or "No scenes.
Try a wider window." This tells the user the result before they apply it.

**Apply = new capture.** **Show imagery** adds a new capture for the same
area and makes it LIVE. It does not change the old capture. This keeps the
captures list for comparison, as the design shows (several dates and cloud
limits for one area). The same request again upserts the existing capture
(`imageryId` is deterministic). **Cancel** closes the popover and changes
nothing.

**Several areas.** **Edit** acts on the area of the live capture. To edit
the parameters for another area, the user switches that area's capture on;
it then becomes the live capture.

**States in the entry body:**

- Searching: the existing `UpdatingBody`, with the text "Searching
  Sentinel-2 scenes…".
- No scenes: the note line, plus two quick fixes as text buttons:
  "Widen to ±30 days" and "Allow 50 % cloud". Each one applies directly.
- AOI too large: the note line "This area is too large for satellite
  imagery. Zoom in to a smaller area." No quick fix.

**Capture row label.** The design says "cloud <50% · 9 tiles". Use the
scene count after the limits, with the word "scenes" (as now), because a
scene and an MGRS tile are not the same thing.

**Reuse.** Build the popover as a generic `ParamEditPopover` (title, a list
of fields, Apply, Cancel). The dataset **Edit** (YEAR, CANOPY) can use it
later.

**Link to the agent (phase 2).** A user edit changes the live capture in
`view_context`, so the agent sees the new parameters on the next message.
The user edit does not send a chat message.

### Feature flag

`NEXT_PUBLIC_IMAGERY_CLIENT_RENDER`. Off: the current tiler path. On: the
client path. We can compare both in staging with the same agent payload.

### Dashboards

Not in phase 1. Dashboard map widgets keep the tile URL. Phase 2 moves them.
`Sentinel2Layers` takes a list of layers, not the map store, so the dashboard
map widget can use it later.

## Spike (1 to 2 days, before phase 1)

Each check can stop or change the plan.

1. CORS and range requests from our staging origin: POST to earth-search,
   and `Range` GETs to `sentinel-cogs.s3.us-west-2.amazonaws.com`.
2. Draw order in `MosaicLayer`: which source draws on top. The nearest date
   must be on top. Reverse the list if necessary.
3. Interleaved `MapboxOverlay` with `beforeId` and our
   `RASTER_TOP_SENTINEL_ID` layer.
4. Speed: a 50,000 km² AOI, 40 scenes, zoom 8 to 12, on a mid-range laptop.
   Count the COG requests and measure the time to first render. Compare
   with the GFW tiler. Use the result to set the three limits.
5. Build: WASM and web workers in deck.gl-geotiff with our Vite config
   (stac-map uses `vite-plugin-wasm` and `vite-plugin-top-level-await`),
   and SSR prerendering with the lazy module.
6. Bundle size of the lazy chunk.

## Spike results (2026-11-25)

Code: project-zeno-next worktree `../project-zeno-next.worktrees/client-imagery`,
branch `spike/client-imagery` (not committed). Test page without auth:
`/spike-imagery.html` (same react-map-gl stack, `RASTER_TOP_SENTINEL_ID`, a
tree cover loss raster as the "dataset" layer). Measured with headless
Chromium and software WebGL (SwiftShader), so render times are pessimistic.
Network numbers are real.

1. **CORS: pass.** earth-search sends `Access-Control-Allow-Origin: *` for
   POST `/search`. The `sentinel-cogs` bucket allows `*`, `HEAD`, `GET` and
   the `range` header, and answers `206`. The bucket sends no
   `Access-Control-Expose-Headers`, so the browser cannot read
   `Content-Range`. The HEAD request in `loadGeoTIFF` is necessary for this
   reason. Checked from the staging console (2026-11-25): the search, HEAD
   and range requests, a module worker, WebAssembly and WebGL2 all work. No
   Content-Security-Policy blocks them.
2. **Draw order: solved with one `MosaicLayer` per rank.** `MosaicLayer`
   gets its sources from a spatial index, so the order of `sources` has no
   effect. A stack of layers, worst rank first, puts rank 0 on top. Test:
   the full stack is pixel-identical to a rank-0-only render; the reversed
   stack differs on 52 % of the pixels.
3. **Interleaved mode: works with a shim.** deck.gl 9.4.2 (and 10.0 alpha)
   reads `map.transform.height` in interleaved mode. maplibre-gl 6 does not
   expose `transform` at runtime, so every frame throws. A small getter on
   the map (`height`, `elevation: 0`) fixes it, and `beforeId` then keeps
   the imagery below the dataset raster. Risk: the shim is not tested with
   pitch or globe; report it to deck.gl. The non-interleaved overlay (what
   stac-map uses) works without a shim, but draws the imagery above all
   MapLibre layers, including dataset rasters and AOI outlines.
4. **Speed**, AOI 2° × 2° in Rondônia (about 48,000 km²), viewport
   1280 × 800:

   | Search | Zoom | Scenes found / kept | COGs opened | Requests | MB | First scene | Settled |
   | --- | --- | --- | --- | --- | --- | --- | --- |
   | ±7 d, < 20 % | 8 | 14 / 14 | 14 | 77 | 9.4 | 2.0 s | ~10 s |
   | ±7 d, < 20 % | 10 | 14 / 14 | 5 | 28 | 8.2 | 2.2 s | ~5 s |
   | ±7 d, < 20 % | 12 | 14 / 14 | 2 | 21 | 8.6 | 2.6 s | ~7 s |
   | ±30 d, < 60 % | 8 | 123 / 36 | 36 | 195 | 30.2 | 4.3 s | ~20 s |

   The STAC search takes 1.0 to 2.8 s. Each COG HEAD takes about 1 s
   (median), and 4 s when 36 COGs queue. The default search is fast enough.
   The loose search at zoom 8 is the slow case.
   Proposal: `maxScenesPerTile` 2, `maxScenes` 24, `minZoom` 8.
5. **Build: pass with one config change.** The GeoTIFF decoder worker uses
   top-level await, so Vite needs `worker: { format: "es" }` (stac-map has
   the same setting). The SSR build and the prerender pass, and deck.gl is
   not in the server bundle.
6. **Bundle:** the lazy imagery chunk is 934 kB (266 kB gzip), plus a
   118 kB LERC WASM file and a small worker. Load it only when an imagery
   layer exists.

Other findings: the MGRS tile key on earth-search items is `grid:code`
(for example `MGRS-20LNP`), not `s2:mgrs_tile`. The `thumbnail` asset is
`preview.jpg` in the same bucket.

## Phase 1 order of work

1. Spike.
2. `request.ts` and `search.ts` with unit tests (no UI).
3. `Sentinel2Layers.tsx` and the `MapboxOverlay` in `Map.tsx`.
4. Store, `showImagery.ts` adapter 1, legend, thumbnail; behind the flag.
5. Imagery filters in the legend (adapter 2), see the section above.
6. `view_context` report.

## Phase 2 (later): agent and cleanup

Contract for the agent payload, so that adapter 3 is a field mapping:

```json
{
  "provider": "sentinel-2",
  "render": "client",
  "imagery_id": "<encode_recipe token>",
  "aois": [{"source": "gadm", "src_id": "...", "name": "..."}],
  "target_date": "2026-11-18",
  "window_days": 7,
  "max_cloud_cover": 20,
  "max_scenes": 40
}
```

Backend work:

- `show_imagery` resolves the defaults and writes this payload. No STAC
  search, no S3. The tool message must not state a scene count. The agent
  reads the result from `view_context` on the next turn
  (`inspect_view_context`, the `SessionContextMiddleware` breadcrumb).
- `add_map_widget`, `imagery_config` and analysis templates
  `_build_imagery` save the recipe. Old widgets: `decode_recipe` on the
  token in their `tile_url` gives the recipe, so a one-off script can
  rewrite them without loss.
- Then delete `src/api/services/mosaic.py` (keep `encode_recipe` /
  `decode_recipe`), `src/api/routers/mosaic.py`, the `MOSAIC_S3_*` settings
  (also in project-zeno-deploy), `cogeo_mosaic` and `pystac_client`. The
  frontend does not call `/mosaic/create`.
- Frontend: remove the flag and the GFW-tiler path for Sentinel-2. Planet
  keeps `tile_url`.

## Trade-offs

Gains: no S3 bucket, credentials or GFW-tiler dependency; `show_imagery`
becomes a tool with no I/O; the user can change the imagery parameters
without the agent.

Losses: the agent sees the search result one turn later; each browser does
its own search and COG reads, with no shared tile cache; a server-side
export of a dashboard cannot use a tile URL for Sentinel-2 imagery.
