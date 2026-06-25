from abc import ABC, abstractmethod

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
    def __init__(self, dataset_id: int):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

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
                "xAxis": "tree_cover_loss_year",
                "yAxis": "area_ha",
            },
            {
                "id": "chart_1",
                "title": "Annual GHG Emissions from Tree Cover Loss",
                "type": "bar",
                "insight": "",
                "data": rows,
                "xAxis": "tree_cover_loss_year",
                "yAxis": "carbon_emissions_MgCO2e",
            },
        ]


class IntegratedAlertsChartGenerator(ChartGenerator):
    """Integrated Alerts: monthly disturbed area, grouped by confidence.

    Aggregates the daily ``area_ha`` rows into one bar per month, colored by
    ``alert_confidence`` (low / high / highest) — there are no driver or
    land-cover intersections to break down by.
    """

    def __init__(self, dataset_id: int):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, result: DataPullResult) -> list[dict]:
        totals: dict[tuple[str, str], float] = {}
        for row in _column_to_rows(result.data):
            month = str(row.get("alert_date", ""))[:7]
            confidence = row.get("alert_confidence", "")
            totals[(month, confidence)] = totals.get(
                (month, confidence), 0
            ) + (row.get("area_ha") or 0)

        data = [
            {"month": month, "alert_confidence": confidence, "area_ha": area}
            for (month, confidence), area in sorted(totals.items())
        ]
        return [
            {
                "id": "chart_0",
                "title": "Integrated Deforestation Alerts by Confidence",
                "type": "bar",
                "insight": "",
                "data": data,
                "xAxis": "month",
                "yAxis": "area_ha",
                "colorField": "alert_confidence",
            }
        ]
