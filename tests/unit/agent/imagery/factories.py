from datetime import date

from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery
from src.shared.imagery.sentinel2 import (
    SceneSummary,
    SearchWindowPeriod,
    Sentinel2Imagery,
)


def planet_imagery(**overrides) -> PlanetImagery:
    defaults = {
        "period": MonthlyPeriod.from_month("2026-08"),
        "tile_url": "https://tiles.example/{z}/{x}/{y}.png",
        "bounds": [-56.0, -8.0, -54.0, -6.0],
        "min_zoom": 10,
        "max_zoom": 18,
        "aoi_names": ["Novo Progresso"],
    }
    return PlanetImagery(**{**defaults, **overrides})


def scene_summary(**overrides) -> SceneSummary:
    defaults = {
        "item_count": 9,
        "start_date": "2026-08-10",
        "end_date": "2026-08-18",
        "mean_cloud_cover": 10.0,
        "min_cloud_cover": 1.0,
        "max_cloud_cover": 20.0,
    }
    return SceneSummary(**{**defaults, **overrides})


def sentinel2_imagery(**overrides) -> Sentinel2Imagery:
    defaults = {
        "period": SearchWindowPeriod.from_search(
            date(2026, 8, 15), window_days=7, today=date(2026, 9, 29)
        ),
        "tile_url": "https://tiles.example/{z}/{x}/{y}.png",
        "tilejson_url": "https://tiles.example/tilejson.json",
        "mosaic_id": "recipe-token",
        "max_cloud_cover": 20,
        "scenes": scene_summary(),
        "aoi_names": ["Odzala-Kokoua"],
    }
    return Sentinel2Imagery(**{**defaults, **overrides})
