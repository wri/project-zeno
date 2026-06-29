"""Deterministic chart generators — rule/config-driven builders that turn
pulled data into `InsightChart`s without calling an LLM.

`AnalyzeService` is injected with a sequence of these and picks the first whose
`can_handle(dataset_id)` matches; datasets with no matching generator yield no
charts.
"""

from abc import ABC, abstractmethod
from typing import List

from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.subagents.analyst.charts import InsightChart


def column_to_rows(data: dict) -> List[dict]:
    """Convert column-oriented data ({col: [..]}) to a list of row dicts."""
    keys = list(data.keys())
    return [dict(zip(keys, values)) for values in zip(*data.values())]


class ChartGenerator(ABC):
    """A deterministic chart builder for one (or more) dataset(s)."""

    @abstractmethod
    def can_handle(self, dataset_id: int) -> bool: ...

    @abstractmethod
    def generate(self, rows: List[dict]) -> List[InsightChart]: ...


class TCLChartGenerator(ChartGenerator):
    """Tree Cover Loss: annual loss area + annual GHG emissions, as two bars."""

    def __init__(self, dataset_id: int = TREE_COVER_LOSS_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        rows = [r for r in rows if r.get("area_ha") != 0]
        return [
            InsightChart(
                position=0,
                title="Annual Tree Cover Loss",
                chart_type="bar",
                x_axis="tree_cover_loss_year",
                y_axis="area_ha",
                chart_data=rows,
            ),
            InsightChart(
                position=1,
                title="Annual GHG Emissions from Tree Cover Loss",
                chart_type="bar",
                x_axis="tree_cover_loss_year",
                y_axis="carbon_emissions_MgCO2e",
                chart_data=rows,
            ),
        ]


class IntegratedAlertsChartGenerator(ChartGenerator):
    """Integrated Alerts: monthly disturbed area, grouped by confidence.

    Aggregates the daily ``area_ha`` rows into one bar per month, colored by
    ``alert_confidence`` (low / high / highest) — there are no driver or
    land-cover intersections to break down by.
    """

    def __init__(self, dataset_id: int = INTEGRATED_ALERTS_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        totals: dict[tuple[str, str], float] = {}
        for row in rows:
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
            InsightChart(
                position=0,
                title="Integrated Deforestation Alerts by Confidence",
                chart_type="bar",
                x_axis="month",
                y_axis="area_ha",
                color_field="alert_confidence",
                chart_data=data,
            )
        ]


DETERMINISTIC_GENERATORS: List[ChartGenerator] = [
    TCLChartGenerator(),
    IntegratedAlertsChartGenerator(),
]
