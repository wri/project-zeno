# Imagery wire contract (v1)

**Status:** the contract the frontend builds against in rollout **phase 1** (see [rollout-plan.md](rollout-plan.md)). Revised in the PR #844 review, before release: it adds `layer_id` and `source`, and removes `tile_url`, `tilejson_url` and Planet's flat `bounds`/`min_zoom`/`max_zoom`. No reader has shipped against the earlier draft, so it stays v1.
**Source of truth:** `src/shared/imagery/wire.py` (`Imagery`), on backend branch `feat/imagery-wire-contract`.
**Robustness principle:** the backend is **strict** when it builds a payload (`extra="forbid"`). The published schema below is **tolerant**: it doesn't set `additionalProperties: false`, so adding a field later is never a breaking change for readers.

## Where the payload appears

| place | path | written by |
|---|---|---|
| `/api/chat` stream | the `update` of a `"node": "tools"` line, JSON-parsed, then `.imagery` | `show_imagery` / `show_planet_imagery` |
| thread replay (`GET /api/threads/{id}`) | the same `update.imagery`, as stored in the checkpoint | replays whatever shape was stored (**may be legacy**) |
| dashboard map widget | `widget.config.imagery` | `add_map_widget`, analysis templates (**may be legacy** for older widgets) |

Each `update` is a JSON string produced by langchain `dumps`. Parse it, then read `.imagery`.

## Shape at a glance

```
Imagery = PlanetImagery | Sentinel2Imagery        discriminated on "provider"

every Imagery                                     # ImageryBase
  provider      "planet" | "sentinel-2"           discriminator, always present
  period        { start: date, end: date }        the time range the layer represents
  aoi_names     string[]
  layer_id      string                            opaque, stable per request: the map layer id
  source        RasterSource                      everything needed to draw the layer

RasterSource                                      the keys of a MapLibre raster source
  tiles         string[]                          XYZ templates ({z}/{x}/{y}); one entry today
  bounds        [west, south, east, north]        exactly 4 numbers; covers the requested areas
  minzoom       integer
  maxzoom       integer

PlanetImagery   (provider = "planet")
  period        calendar month (1st → last day)
  (zooms 10–18)

Sentinel2Imagery (provider = "sentinel-2")
  period        search window: target ± window_days, end never after the search day
  mosaic_id     string                            opaque recipe token, stable per request
  max_cloud_cover integer                         the cloud-cover LIMIT the search used (%)
  scenes        SceneSummary | null               ALWAYS present; null for old cached mosaics
  (zooms 8–14, the mosaic's own)

SceneSummary
  item_count        integer
  start_date        date                          first scene actually captured
  end_date          date                          last scene actually captured
  mean_cloud_cover  number                        observed across the scenes (%)
  min_cloud_cover   number
  max_cloud_cover   number                        OBSERVED maximum, not the search limit
```

Dates are ISO `YYYY-MM-DD` strings. There are no optional keys: every key listed is always present. `scenes` is the only value that can be `null`.

## Rules for readers (tolerant reader)

1. **Tell the contract from legacy by `period`.** If `"period"` is present, the payload is contract v1. If not, it's the legacy flat shape (see [Legacy shape](#legacy-shape-still-to-be-read-in-phase-1)). Replayed threads and older widgets will send legacy payloads for a long time.
2. **Switch on `provider`.** It's required, and it's the only way to tell the two period types apart: they look the same on the wire.
3. **Treat an unknown `provider` as "imagery I can't render"**: skip the layer and keep the rest of the UI working. New providers will be added to the union.
4. **Ignore fields you don't know about.** Don't validate with `additionalProperties: false`.
5. **`scenes: null` means "no scene statistics"**, not an error. Hide the count, capture dates and cloud cover.
6. **Two kinds of dates, and they mean different things:**
   - `period.start` → `period.end`: the range the layer was *built for* (a Planet month, or a Sentinel-2 search window). Use this to describe the layer.
   - `scenes.start_date` → `scenes.end_date`: when the scenes were *actually captured*. Use this for "Acquired" or "Scenes from" labels.
   - Legacy Sentinel-2 `start_date`/`end_date` meant the **captured** range, so they correspond to `scenes.*`, not `period.*`.
7. **Layer identity is `layer_id`.** Use it as the map layer and source id. It's opaque: don't parse it. The same request always gives the same `layer_id`, so a replayed or repeated call updates the layer instead of adding a second one. Different areas or months give different ids. (Sentinel-2's `layer_id` happens to equal its `mosaic_id` today; don't rely on that.)
8. **Two different `max_cloud_cover` fields.** `Sentinel2Imagery.max_cloud_cover` is the search *limit* (an integer %). `scenes.max_cloud_cover` is the *observed* maximum (a number %). The legacy `max_cloud_cover_observed` is now `scenes.max_cloud_cover`.
9. **Draw the layer from `source`.** It has the keys of a MapLibre raster source (`tiles`, `bounds`, `minzoom`, `maxzoom`), so it can be spread into `map.addSource(layer_id, { type: "raster", ...source })`. `tiles` is a list of XYZ templates (`{z}/{x}/{y}`) and has one entry today. `bounds` is `[west, south, east, north]` and covers the requested areas. There's no TileJSON to fetch. `tileSize` isn't part of the contract.

## Examples

Both examples are real provider output (the S3 part of the Sentinel-2 URL is shortened).

### Planet

```json
{
  "provider": "planet",
  "period": {
    "start": "2026-08-01",
    "end": "2026-08-31"
  },
  "aoi_names": [
    "Novo Progresso"
  ],
  "layer_id": "bbddba21393743b3",
  "source": {
    "tiles": [
      "https://tiles.globalforestwatch.org/integrated_alerts_planet_imagery/{z}/{x}/{y}.png?month=2026-08"
    ],
    "bounds": [-56.0, -8.0, -54.0, -6.0],
    "minzoom": 10,
    "maxzoom": 18
  }
}
```

### Sentinel-2

The search ran on 2026-09-29, with target 2026-09-25 and a 7-day window, so the end of the window is clamped to the search day.

```json
{
  "provider": "sentinel-2",
  "period": {
    "start": "2026-09-18",
    "end": "2026-09-29"
  },
  "aoi_names": [
    "Vaud"
  ],
  "layer_id": "eyJhIjpbWyJnYWRtIiwiQ0hFLjI2XzEiXV0sImQiOiIyMDI2LTA5LTI1In0",
  "source": {
    "tiles": [
      "https://tiles.globalforestwatch.org/cog/mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=s3%3A%2F%2F...%2FeyJhIjpbWyJnYWRtIiwiQ0hFLjI2XzEiXV0sImQiOiIyMDI2LTA5LTI1In0.json"
    ],
    "bounds": [6.0, 46.2, 7.2, 46.9],
    "minzoom": 8,
    "maxzoom": 14
  },
  "mosaic_id": "eyJhIjpbWyJnYWRtIiwiQ0hFLjI2XzEiXV0sImQiOiIyMDI2LTA5LTI1In0",
  "max_cloud_cover": 20,
  "scenes": {
    "item_count": 6,
    "start_date": "2026-09-19",
    "end_date": "2026-09-28",
    "mean_cloud_cover": 7.35,
    "min_cloud_cover": 2.1,
    "max_cloud_cover": 14.8
  }
}
```

### Sentinel-2 from an old cached mosaic

The same payload, except for `"scenes": null`.

## TypeScript types (suggested)

```ts
export type ImageryV1 = PlanetImageryV1 | Sentinel2ImageryV1;

export interface RasterSourceV1 {
  tiles: string[];
  bounds: [number, number, number, number];
  minzoom: number;
  maxzoom: number;
}

interface ImageryBaseV1 {
  provider: string;
  period: { start: string; end: string };
  aoi_names: string[];
  layer_id: string;
  source: RasterSourceV1;
}

export interface PlanetImageryV1 extends ImageryBaseV1 {
  provider: "planet";
}

export interface SceneSummaryV1 {
  item_count: number;
  start_date: string;
  end_date: string;
  mean_cloud_cover: number;
  min_cloud_cover: number;
  max_cloud_cover: number;
}

export interface Sentinel2ImageryV1 extends ImageryBaseV1 {
  provider: "sentinel-2";
  mosaic_id: string;
  max_cloud_cover: number;
  scenes: SceneSummaryV1 | null;
}

export const isImageryV1 = (payload: object): boolean => "period" in payload;
```

## JSON Schema (tolerant, draft 2020-12)

The published schema is **[`imagery.schema.json`](imagery.schema.json)**. It's built in code by `src.shared.imagery.wire.json_schema()`, from `TypeAdapter(Imagery).json_schema(mode="serialization")`, made tolerant:
- `additionalProperties: false` is removed from every object schema;
- `provider` is required, because the backend always sends it (`json_schema_serialization_defaults_required` on `StrictModel`; pydantic otherwise leaves fields that have defaults out of `required`);
- field-level `title`s are removed.

`tests/unit/agent/imagery/test_published_schema.py` fails whenever the code's schema and the file disagree, so a contract change can't ship without updating the published file. After an intended change, regenerate it:

```sh
.venv/bin/python -c "import json; from src.shared.imagery.wire import json_schema; print(json.dumps(json_schema(), indent=2))" > docs/imagery/imagery.schema.json
```

Checked with `jsonschema`: the examples above and a `scenes: null` payload are valid, a payload with an extra field is valid, and a payload without `provider` is rejected.

## Legacy shape (still to be read in phase 1)

This is the flat `ImageryState` payload, sent by today's backend and by every replayed thread and older widget. The frontend already types it as `ImageryInfo` (`project-zeno-next/app/types/chat.ts`). Every field is optional or nullable, and `provider` may be missing (meaning Sentinel-2).

| legacy field | contract v1 |
|---|---|
| `provider` (missing → `"sentinel-2"`) | `provider` |
| `tile_url` | `source.tiles[0]` |
| `aoi_names` | `aoi_names` |
| `tilejson_url` | **no field**: bounds and zooms are in `source` |
| `bounds`, `min_zoom`, `max_zoom` (Planet) | `source.bounds`, `source.minzoom`, `source.maxzoom` |
| `mosaic_id` | Sentinel-2 `mosaic_id`, and its `layer_id`; Planet's `"planet:YYYY-MM"` → **no field** (the month is in `period`; the layer id is `layer_id`) |
| `start_date` / `end_date` (or `date_start` / `date_end`) | **Planet:** `period.start` / `period.end`. **Sentinel-2:** `scenes.start_date` / `scenes.end_date` (captured range) |
| `target_date`, `window_days` | Sentinel-2 `period` (target ± window) |
| `item_count`, `mean_cloud_cover`, `min_cloud_cover` | `scenes.item_count`, `scenes.mean_cloud_cover`, `scenes.min_cloud_cover` |
| `max_cloud_cover_observed` | `scenes.max_cloud_cover` |
| `max_cloud_cover` | Sentinel-2 `max_cloud_cover` (search limit) |

In phase 3 the backend converts legacy payloads to v1 on read, so after phase 4 the frontend reads only v1. Two legacy gaps the converter has to fill:
- **Legacy Sentinel-2 has no bounds.** Use the mosaic zooms (8–14) and either the mosaic's TileJSON `bounds` (from `tilejson_url`) or the world bbox.
- **Legacy payloads have no AOI refs**, only `aoi_names`, so Planet's `layer_id` (a hash of the month and the `(source, src_id)` refs) can't be recomputed. The converter needs its own stable id (for example from the month and the names); it only has to be stable, not equal to what the provider would send today.

## Changing the contract

- **Adding** a field or a provider is compatible, under the tolerant reader rules above.
- **Renaming, removing, or changing the type or meaning of** a field is breaking. It needs a new expand/contract rollout, and a new version (`v2`) of this document.
