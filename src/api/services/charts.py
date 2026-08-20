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
    LAND_GHG_INVENTORY_ID,
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
        # The analytics API returns rows in arbitrary order; sort by year so
        # the chart's category x-axis reads 2001 → 2025 rather than a shuffle.
        rows = sorted(
            (r for r in rows if r.get("area_ha") != 0),
            key=lambda r: r.get("tree_cover_loss_year") or 0,
        )
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
    """Integrated alerts: monthly disturbed area over time, by confidence.

    Aggregates the daily ``area_ha`` rows into a monthly line per
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
                chart_type="line",
                x_axis="month",
                y_axis="area_ha",
                color_field="alert_confidence",
                chart_data=data,
            )
        ]


LGMS_FULL_SERIES_CLASS_ORDER = [
    "tree_loss",
    "trees_remaining_trees",
    "non_trees_remaining_non_trees",
    "mineral_soil",
    "organic_soil",
    "cropland",
    "livestock",
    "tree_gain",
]


class LGMSChartGenerator(ChartGenerator):
    """Land GHG Monitoring System: three stacked-bar-with-line charts at
    increasing levels of aggregation — full detail (per raw class and measure),
    category (vegetation/soil/agriculture split into emissions vs. removals),
    and summary (land use vs. agriculture).

    Input rows come from `merge_lgms_sections()`
    (src/agent/datasets/handlers/analytics_handler.py), one row per
    (category, class, year). Emissions are always positive, removals always
    negative, but — confirmed by
    tests/tools/test_analytics_handler.py::test_merge_lgms_sections_flattens_to_category_class_table
    — a vegetation row can have BOTH `gross_emissions_MgCO2e` and
    `gross_removals_MgCO2` populated at once (e.g. a "tree gain" row still
    carries a 0-or-positive emissions figure alongside its removals), so the
    full-detail chart treats each (class, metric) pair as its own series
    rather than assuming one metric per class. Category/summary aggregation
    sums both metrics independently per category and isn't affected by this.
    All three charts pivot the long input into wide (one row per year, one
    column per series) at increasing levels of folding — no single-value
    "net" chart is produced here, and no color/hatch styling is attached: both
    are pure presentation concerns left to the frontend, which derives them
    arithmetically from whichever chart is selected.
    """

    def __init__(self, dataset_id: int = LAND_GHG_INVENTORY_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        by_year: dict[int, List[dict]] = {}
        for row in rows:
            by_year.setdefault(int(row.get("year") or 0), []).append(row)

        full_rows = []
        category_rows = []
        for year in sorted(by_year):
            year_rows = by_year[year]

            full_row: dict = {"year": year}
            for row in year_rows:
                class_name = row.get("class")
                emissions = row.get("gross_emissions_MgCO2e")
                if emissions is not None:
                    key = f"{class_name}_emissions"
                    full_row[key] = full_row.get(key, 0) + emissions
                removals = row.get("gross_removals_MgCO2")
                if removals is not None:
                    key = f"{class_name}_removals"
                    full_row[key] = full_row.get(key, 0) + removals
            full_rows.append(full_row)

            vegetation = [
                r for r in year_rows if r.get("category") == "vegetation"
            ]
            soil = [r for r in year_rows if r.get("category") == "soil"]
            agriculture = [
                r for r in year_rows if r.get("category") == "agriculture"
            ]

            category_rows.append(
                {
                    "year": year,
                    "vegetation_emissions": sum(
                        r.get("gross_emissions_MgCO2e") or 0
                        for r in vegetation
                    ),
                    "vegetation_removals": sum(
                        r.get("gross_removals_MgCO2") or 0 for r in vegetation
                    ),
                    "soil_emissions": sum(
                        r.get("gross_emissions_MgCO2e") or 0 for r in soil
                    ),
                    "soil_removals": sum(
                        r.get("gross_removals_MgCO2") or 0 for r in soil
                    ),
                    "cropland_emissions": sum(
                        r.get("gross_emissions_MgCO2e") or 0
                        for r in agriculture
                        if r.get("class") == "cropland"
                    ),
                    "livestock_emissions": sum(
                        r.get("gross_emissions_MgCO2e") or 0
                        for r in agriculture
                        if r.get("class") == "livestock"
                    ),
                }
            )

        summary_rows = [
            {
                "year": row["year"],
                "land_use_emissions": row["vegetation_emissions"]
                + row["soil_emissions"],
                "agriculture_emissions": row["cropland_emissions"]
                + row["livestock_emissions"],
                "land_use_removals": row["vegetation_removals"]
                + row["soil_removals"],
            }
            for row in category_rows
        ]

        seen_series: dict = {}
        for row in full_rows:
            for series_name in row:
                if series_name != "year":
                    seen_series.setdefault(series_name, None)
        spec_order = [
            f"{class_name}_{suffix}"
            for suffix in ("emissions", "removals")
            for class_name in LGMS_FULL_SERIES_CLASS_ORDER
        ]
        full_series_fields = [s for s in spec_order if s in seen_series] + [
            s for s in seen_series if s not in spec_order
        ]

        return [
            InsightChart(
                position=0,
                title="Net GHG Flux — Full Detail",
                chart_type="stacked-bar-with-line",
                x_axis="year",
                series_fields=full_series_fields,
                chart_data=full_rows,
            ),
            InsightChart(
                position=1,
                title="Net GHG Flux by Category",
                chart_type="stacked-bar-with-line",
                x_axis="year",
                series_fields=[
                    "vegetation_emissions",
                    "soil_emissions",
                    "cropland_emissions",
                    "livestock_emissions",
                    "vegetation_removals",
                    "soil_removals",
                ],
                chart_data=category_rows,
            ),
            InsightChart(
                position=2,
                title="Net GHG Flux Summary",
                chart_type="stacked-bar-with-line",
                x_axis="year",
                series_fields=[
                    "land_use_emissions",
                    "agriculture_emissions",
                    "land_use_removals",
                ],
                chart_data=summary_rows,
            ),
        ]


DETERMINISTIC_GENERATORS: List[ChartGenerator] = [
    TCLChartGenerator(),
    IntegratedAlertsChartGenerator(),
    LGMSChartGenerator(),
]
