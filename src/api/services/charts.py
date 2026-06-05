from abc import ABC, abstractmethod

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_LOSS_ID
from src.agent.datasets.handlers.base import DataPullResult


class ChartGenerator(ABC):
    @abstractmethod
    def can_handle(self, dataset_id: int) -> bool:
        pass

    @abstractmethod
    def generate(self, result: DataPullResult) -> list[dict]:
        pass


def _column_to_rows(data: dict) -> list[dict]:
    keys = list(data.keys())
    return [dict(zip(keys, values)) for values in zip(*data.values())]


class TCLChartGenerator(ChartGenerator):
    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == TREE_COVER_LOSS_ID

    def generate(self, result: DataPullResult) -> list[dict]:
        rows = [
            r for r in _column_to_rows(result.data) if r.get("area_ha") != 0
        ]
        return [
            {
                "id": "chart_0",
                "title": "Annual Tree Cover Loss",
                "type": "bar",
                "insight": "",
                "data": rows,
                "xAxis": "year",
                "yAxis": "area_ha",
            },
            {
                "id": "chart_1",
                "title": "Annual GHG Emissions from Tree Cover Loss",
                "type": "bar",
                "insight": "",
                "data": rows,
                "xAxis": "year",
                "yAxis": "emissions_MgCO2e",
            },
        ]
