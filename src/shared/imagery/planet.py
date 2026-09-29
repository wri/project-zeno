import calendar
from datetime import date
from typing import Literal

from src.shared.imagery.contract import LayerPeriod, StrictModel


class MonthlyPeriod(LayerPeriod):
    @classmethod
    def from_month(cls, month: str) -> "MonthlyPeriod":
        start = date.fromisoformat(f"{month}-01")
        last_day = calendar.monthrange(start.year, start.month)[1]
        return cls(start=start, end=start.replace(day=last_day))


class PlanetImagery(StrictModel):
    provider: Literal["planet"] = "planet"
    period: MonthlyPeriod
    tile_url: str
    bounds: tuple[float, float, float, float]
    min_zoom: int
    max_zoom: int
    aoi_names: list[str]
