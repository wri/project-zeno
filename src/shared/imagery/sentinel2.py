from datetime import date, timedelta
from typing import Literal, Optional

from src.shared.imagery.contract import ImageryBase, LayerPeriod, StrictModel


class SearchWindowPeriod(LayerPeriod):
    @classmethod
    def from_search(
        cls, target_date: date, window_days: int, today: date
    ) -> "SearchWindowPeriod":
        window = timedelta(days=window_days)
        return cls(
            start=target_date - window, end=min(target_date + window, today)
        )


class SceneSummary(StrictModel):
    item_count: int
    start_date: date
    end_date: date
    mean_cloud_cover: float
    min_cloud_cover: float
    max_cloud_cover: float


class Sentinel2Imagery(ImageryBase):
    provider: Literal["sentinel-2"] = "sentinel-2"
    period: SearchWindowPeriod
    mosaic_id: str
    max_cloud_cover: int
    scenes: Optional[SceneSummary]

    def label(self) -> str:
        if self.scenes is None:
            return super().label()
        return f"{super().label()} ({self.scenes.item_count} scenes)"
