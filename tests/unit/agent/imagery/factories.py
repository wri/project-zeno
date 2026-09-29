from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery


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
