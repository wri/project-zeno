from datetime import date, timedelta

from src.shared.imagery.contract import LayerPeriod, StrictModel


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
