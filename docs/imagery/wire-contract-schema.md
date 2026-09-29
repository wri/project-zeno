# Imagery wire contract (v1)

**Status:** the contract the frontend builds against in rollout **phase 1** (see [rollout-plan.md](rollout-plan.md)).
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
  tile_url      string                            XYZ template ({z}/{x}/{y})
  aoi_names     string[]

PlanetImagery   (provider = "planet")
  period        calendar month (1st → last day)
  bounds        [west, south, east, north]        exactly 4 numbers
  min_zoom      integer
  max_zoom      integer

Sentinel2Imagery (provider = "sentinel-2")
  period        search window: target ± window_days, end never after the search day
  tilejson_url  string                            fetch for bounds / zooms
  mosaic_id     string                            opaque recipe token, stable per request
  max_cloud_cover integer                         the cloud-cover LIMIT the search used (%)
  scenes        SceneSummary | null               ALWAYS present; null for old cached mosaics

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
7. **Layer identity.** Sentinel-2 has `mosaic_id`, which is stable per request. **Planet has no `mosaic_id`**, so derive the layer id from `tile_url`, which is unique per month.
8. **Two different `max_cloud_cover` fields.** `Sentinel2Imagery.max_cloud_cover` is the search *limit* (an integer %). `scenes.max_cloud_cover` is the *observed* maximum (a number %). The legacy `max_cloud_cover_observed` is now `scenes.max_cloud_cover`.

## Examples

### Planet

```json
{
  "provider": "planet",
  "period": { "start": "2026-08-01", "end": "2026-08-31" },
  "tile_url": "https://tiles.globalforestwatch.org/integrated_alerts_planet_imagery/{z}/{x}/{y}.png?month=2026-08",
  "aoi_names": ["Novo Progresso"],
  "bounds": [-56.0, -8.0, -54.0, -6.0],
  "min_zoom": 10,
  "max_zoom": 18
}
```

### Sentinel-2

The search ran on 2026-09-29, with target 2026-09-25 and a 7-day window, so the end of the window is clamped to the search day.

```json
{
  "provider": "sentinel-2",
  "period": { "start": "2026-09-18", "end": "2026-09-29" },
  "tile_url": "https://tiles.globalforestwatch.org/cog/mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=s3%3A%2F%2F...%2Feyj9.json",
  "aoi_names": ["Vaud"],
  "tilejson_url": "https://tiles.globalforestwatch.org/cog/mosaic/WebMercatorQuad/tilejson.json?url=s3%3A%2F%2F...%2Feyj9.json",
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

interface ImageryBaseV1 {
  provider: string;
  period: { start: string; end: string };
  tile_url: string;
  aoi_names: string[];
}

export interface PlanetImageryV1 extends ImageryBaseV1 {
  provider: "planet";
  bounds: [number, number, number, number];
  min_zoom: number;
  max_zoom: number;
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
  tilejson_url: string;
  mosaic_id: string;
  max_cloud_cover: number;
  scenes: SceneSummaryV1 | null;
}

export const isImageryV1 = (payload: object): boolean => "period" in payload;
```

## JSON Schema (tolerant, draft 2020-12)

Generated from `TypeAdapter(Imagery).json_schema(mode="serialization")`, then made tolerant:
- `additionalProperties: false` removed from all 5 object schemas;
- `provider` added to `required`, because the backend always sends it. Pydantic doesn't mark fields that have defaults as required. Follow-up: set `json_schema_serialization_defaults_required` in code and add a schema snapshot test;
- field-level `title`s removed.

Checked with `jsonschema`: real Planet, Sentinel-2 and `scenes: null` payloads are valid, a payload with an extra field is valid, and a payload without `provider` is rejected.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "imagery.schema.json",
  "title": "Imagery",
  "$defs": {
    "MonthlyPeriod": {
      "properties": {
        "start": {
          "format": "date",
          "type": "string"
        },
        "end": {
          "format": "date",
          "type": "string"
        }
      },
      "required": [
        "start",
        "end"
      ],
      "title": "MonthlyPeriod",
      "type": "object"
    },
    "PlanetImagery": {
      "properties": {
        "provider": {
          "const": "planet",
          "type": "string"
        },
        "period": {
          "$ref": "#/$defs/MonthlyPeriod"
        },
        "tile_url": {
          "type": "string"
        },
        "aoi_names": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "bounds": {
          "maxItems": 4,
          "minItems": 4,
          "prefixItems": [
            {
              "type": "number"
            },
            {
              "type": "number"
            },
            {
              "type": "number"
            },
            {
              "type": "number"
            }
          ],
          "type": "array"
        },
        "min_zoom": {
          "type": "integer"
        },
        "max_zoom": {
          "type": "integer"
        }
      },
      "required": [
        "provider",
        "period",
        "tile_url",
        "aoi_names",
        "bounds",
        "min_zoom",
        "max_zoom"
      ],
      "title": "PlanetImagery",
      "type": "object"
    },
    "SceneSummary": {
      "properties": {
        "item_count": {
          "type": "integer"
        },
        "start_date": {
          "format": "date",
          "type": "string"
        },
        "end_date": {
          "format": "date",
          "type": "string"
        },
        "mean_cloud_cover": {
          "type": "number"
        },
        "min_cloud_cover": {
          "type": "number"
        },
        "max_cloud_cover": {
          "type": "number"
        }
      },
      "required": [
        "item_count",
        "start_date",
        "end_date",
        "mean_cloud_cover",
        "min_cloud_cover",
        "max_cloud_cover"
      ],
      "title": "SceneSummary",
      "type": "object"
    },
    "SearchWindowPeriod": {
      "properties": {
        "start": {
          "format": "date",
          "type": "string"
        },
        "end": {
          "format": "date",
          "type": "string"
        }
      },
      "required": [
        "start",
        "end"
      ],
      "title": "SearchWindowPeriod",
      "type": "object"
    },
    "Sentinel2Imagery": {
      "properties": {
        "provider": {
          "const": "sentinel-2",
          "type": "string"
        },
        "period": {
          "$ref": "#/$defs/SearchWindowPeriod"
        },
        "tile_url": {
          "type": "string"
        },
        "aoi_names": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "tilejson_url": {
          "type": "string"
        },
        "mosaic_id": {
          "type": "string"
        },
        "max_cloud_cover": {
          "type": "integer"
        },
        "scenes": {
          "anyOf": [
            {
              "$ref": "#/$defs/SceneSummary"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "provider",
        "period",
        "tile_url",
        "aoi_names",
        "tilejson_url",
        "mosaic_id",
        "max_cloud_cover",
        "scenes"
      ],
      "title": "Sentinel2Imagery",
      "type": "object"
    }
  },
  "discriminator": {
    "mapping": {
      "planet": "#/$defs/PlanetImagery",
      "sentinel-2": "#/$defs/Sentinel2Imagery"
    },
    "propertyName": "provider"
  },
  "oneOf": [
    {
      "$ref": "#/$defs/PlanetImagery"
    },
    {
      "$ref": "#/$defs/Sentinel2Imagery"
    }
  ]
}
```

## Legacy shape (still to be read in phase 1)

This is the flat `ImageryState` payload, sent by today's backend and by every replayed thread and older widget. The frontend already types it as `ImageryInfo` (`project-zeno-next/app/types/chat.ts`). Every field is optional or nullable, and `provider` may be missing (meaning Sentinel-2).

| legacy field | contract v1 |
|---|---|
| `provider` (missing → `"sentinel-2"`) | `provider` |
| `tile_url` | `tile_url` |
| `aoi_names` | `aoi_names` |
| `tilejson_url` | Sentinel-2 `tilejson_url` |
| `bounds`, `min_zoom`, `max_zoom` | Planet `bounds`, `min_zoom`, `max_zoom` |
| `mosaic_id` | Sentinel-2 `mosaic_id`; Planet's `"planet:YYYY-MM"` → **no field** (the month is in `period`) |
| `start_date` / `end_date` (or `date_start` / `date_end`) | **Planet:** `period.start` / `period.end`. **Sentinel-2:** `scenes.start_date` / `scenes.end_date` (captured range) |
| `target_date`, `window_days` | Sentinel-2 `period` (target ± window) |
| `item_count`, `mean_cloud_cover`, `min_cloud_cover` | `scenes.item_count`, `scenes.mean_cloud_cover`, `scenes.min_cloud_cover` |
| `max_cloud_cover_observed` | `scenes.max_cloud_cover` |
| `max_cloud_cover` | Sentinel-2 `max_cloud_cover` (search limit) |

In phase 3 the backend converts legacy payloads to v1 on read, so after phase 4 the frontend reads only v1.

## Changing the contract

- **Adding** a field or a provider is compatible, under the tolerant reader rules above.
- **Renaming, removing, or changing the type or meaning of** a field is breaking. It needs a new expand/contract rollout, and a new version (`v2`) of this document.
