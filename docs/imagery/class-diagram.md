# Imagery wire contract: classes

The backend model behind the `imagery` value in `/api/chat` tool updates and in dashboard map-widget configs. Why it's shaped this way: [ADR 0001](../adr/0001-imagery-wire-contract.md). Payload reference for readers: [wire-contract-schema.md](wire-contract-schema.md).

```mermaid
%%{init: {"layout": "elk", "elk": {"nodePlacementStrategy": "NETWORK_SIMPLEX", "mergeEdges": false}}}%%
classDiagram
    direction BT

    class wire {
        <<module>>
        Imagery = Annotated~PlanetImagery | Sentinel2Imagery~
        discriminator = provider
        +from_payload(dict)$ Optional~Imagery~
    }

    class StrictModel {
        <<abstract>>
        model_config: extra = forbid
        model_post_init() «refuses classes marked abstract»
    }

    class LayerPeriod {
        <<abstract>>
        +start: date
        +end: date
        +label() str «start → end»
    }

    class MonthlyPeriod {
        +from_month(month: str)$ MonthlyPeriod
    }

    class SearchWindowPeriod {
        +from_search(target_date, window_days, today)$ SearchWindowPeriod
    }

    class RasterSource {
        +tiles: list~str~ «XYZ templates»
        +bounds: tuple «w, s, e, n»
        +minzoom: int
        +maxzoom: int
    }

    class ImageryBase {
        <<abstract>>
        +provider: str
        +period: LayerPeriod
        +aoi_names: list~str~
        +layer_id: str «opaque, stable per request»
        +source: RasterSource
        +label() str «provider period»
    }

    class PlanetImagery {
        +provider: Literal~"planet"~
        +period: MonthlyPeriod
    }

    class Sentinel2Imagery {
        +provider: Literal~"sentinel-2"~
        +period: SearchWindowPeriod
        +mosaic_id: str
        +max_cloud_cover: int «search limit»
        +scenes: Optional~SceneSummary~ «required, nullable»
        +label() str «appends the scene count»
    }

    class SceneSummary {
        +item_count: int
        +start_date: date
        +end_date: date
        +mean_cloud_cover: float
        +min_cloud_cover: float
        +max_cloud_cover: float «observed»
    }

    class ImageryProviderResult {
        +status: Literal~"success", "error"~
        +message: str
        +imagery: Optional~Imagery~
    }

    class ImageryProvider {
        <<Protocol>>
        +get_imagery(ImageryRequest) ImageryProviderResult
    }

    class PlanetImageryProvider {
        layer_id «hash of month and sorted AOI refs»
        source «AOI bbox union, zooms 10 to 18»
    }
    class Sentinel2ImageryProvider {
        layer_id «= mosaic_id»
        source «AOI bbox union, mosaic zooms 8 to 14»
    }

    LayerPeriod --|> StrictModel
    ImageryBase --|> StrictModel
    SceneSummary --|> StrictModel
    RasterSource --|> StrictModel
    MonthlyPeriod --|> LayerPeriod
    SearchWindowPeriod --|> LayerPeriod
    PlanetImagery --|> ImageryBase
    Sentinel2Imagery --|> ImageryBase
    LayerPeriod --* ImageryBase : period
    RasterSource --* ImageryBase : source
    MonthlyPeriod --* PlanetImagery : narrows period
    SearchWindowPeriod --* Sentinel2Imagery : narrows period
    SceneSummary "0..1" --* Sentinel2Imagery : scenes
    wire ..> PlanetImagery : one of
    wire ..> Sentinel2Imagery : one of

    PlanetImageryProvider ..|> ImageryProvider
    Sentinel2ImageryProvider ..|> ImageryProvider
    PlanetImageryProvider ..> PlanetImagery : builds
    Sentinel2ImageryProvider ..> Sentinel2Imagery : builds
    ImageryProviderResult <.. ImageryProvider : returns
    ImageryProviderResult o-- wire : imagery
```

## Modules

| module | holds | may be imported by |
|---|---|---|
| `src/shared/imagery/contract.py` | `StrictModel`, `LayerPeriod`, `RasterSource`, `ImageryBase` | anyone |
| `src/shared/imagery/wire.py` | `Imagery`, `from_payload` | anyone. **This is what consumers depend on** |
| `src/shared/imagery/planet.py` | `MonthlyPeriod`, `PlanetImagery` | `wire` and `src/agent/imagery/planet.py` only |
| `src/shared/imagery/sentinel2.py` | `SearchWindowPeriod`, `SceneSummary`, `Sentinel2Imagery` | `wire` and `src/agent/imagery/sentinel2.py` only |

The import boundary in the last two rows is enforced by `tests/architecture/test_imagery_contract_boundaries.py`.

**Readers** go through `wire.from_payload`, which returns contract imagery, or `None` for a legacy payload so the caller can fall back:
- `api/services/widget_configs.imagery_config`
- `agent/middleware.format_session_block`
- `agent/tools/inspect_view_context._format_map_widget`

`api/schemas.DashboardWidgetCreateRequest` doesn't read the contract. It only checks that a map widget's layer has tiles: a `tile_url` (datasets and legacy imagery) or `source.tiles` (contract imagery).

The analysis-template builder reads `ImageryProviderResult.imagery` directly.

**Writer:** `agent/tools/show_imagery.provider_command` puts `imagery.model_dump(mode="json")` into the state update.

## Coupling (internal modules; I = Ce/(Ca+Ce), D = |A + I − 1|)

| module | Ca | Ce | I | A | D |
|---|---|---|---|---|---|
| `contract.py` | 4 | 0 | 0 | 0.67 | 0.33 |
| `wire.py` | 4 | 2 | 0.33 | 1 | 0.33 |
| `planet.py` | 2 | 1 | 0.33 | 0 | 0.67 |
| `sentinel2.py` | 2 | 1 | 0.33 | 0 | 0.67 |

`contract.py`'s Ca counts `planet`, `sentinel2` and both agent providers (which build `RasterSource`). `RasterSource` is a concrete value object, so A is 2 of 3 classes. The union has to import every specialist, so the specialists can't reach I = 1. The import boundary keeps the list of modules that depend on them as short as possible.

## Notes

- **Periods store `start`/`end`** and don't take other fields. Each factory computes them once. `from_search` clamps the end to the day of the search, and the same rule is used by `mosaic.search_window`; the two are tied together by `tests/unit/agent/imagery/test_search_window_consistency.py`.
- **`abstract: ClassVar[bool] = True`** on `LayerPeriod` and `ImageryBase` turns on `StrictModel`'s guard for that class only; subclasses can be built. The flag isn't serialized.
- **`layer_id`** is opaque and required. Sentinel-2 uses its `mosaic_id`. Planet uses the first 16 hex digits of `sha256(json([month, sorted (source, src_id) refs]))`, so the same request always gets the same id, and different areas or months get different ids.
- **`source`** is the only place a layer says how to draw itself. Both providers build `bounds` from the union of the AOI bboxes (`agent/imagery/base.aoi_bounds`). The Sentinel-2 zooms are `mosaic.MOSAIC_MINZOOM`/`MOSAIC_MAXZOOM`, the same values the mosaic is built with.
- **`scenes`** is either a complete `SceneSummary` or `None`. The provider returns `None` unless the mosaic has every scene statistic.
