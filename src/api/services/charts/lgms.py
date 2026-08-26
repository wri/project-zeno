"""Land GHG Monitoring System (LGMS) chart generator."""

from collections import defaultdict
from typing import List

import numpy as np

from src.agent.datasets.handlers.analytics_handler import LAND_GHG_INVENTORY_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import (
    ChartGenerator,
    _fold_metric,
    _metric_values,
    _sum_metric,
)

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

# Human labels for the hierarchical chart's leaf nodes, keyed by raw `class`.
LGMS_CLASS_LABELS = {
    "tree_loss": "Tree loss",
    "tree_gain": "Tree gain",
    "trees_remaining_trees": "Trees remaining trees",
    "non_trees_remaining_non_trees": "Non-trees remaining non-trees",
    "mineral_soil": "Mineral soil",
    "organic_soil": "Organic soil",
}


class LGMSChartGenerator(ChartGenerator):
    """Land GHG Monitoring System: four charts per analysis.

    Three stacked-bar-with-line time series at increasing levels of
    aggregation (full detail, category, summary), plus one hierarchical-bar
    chart of period-of-record averages (see `_hierarchy_rows`). Net flux and
    chart styling are left to the frontend to derive.

    Input is one row per (category, class, year), with emissions always
    positive and removals always negative. A row can carry both metrics at
    once (e.g. "tree gain" has a small positive emissions figure alongside
    its removals), so the full-detail chart treats each (class, metric) pair
    as its own series rather than assuming one metric per class.
    """

    def __init__(self, dataset_id: int = LAND_GHG_INVENTORY_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        by_year: dict[int, List[dict]] = defaultdict(list)
        for row in rows:
            year: int = row["year"]
            by_year[year].append(row)

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

            cropland = [r for r in agriculture if r.get("class") == "cropland"]
            livestock = [
                r for r in agriculture if r.get("class") == "livestock"
            ]

            category_rows.append(
                {
                    "year": year,
                    "vegetation_emissions": _sum_metric(
                        vegetation, "gross_emissions_MgCO2e"
                    ),
                    "vegetation_removals": _sum_metric(
                        vegetation, "gross_removals_MgCO2"
                    ),
                    "soil_emissions": _sum_metric(
                        soil, "gross_emissions_MgCO2e"
                    ),
                    "soil_removals": _sum_metric(soil, "gross_removals_MgCO2"),
                    "cropland_emissions": _sum_metric(
                        cropland, "gross_emissions_MgCO2e"
                    ),
                    "livestock_emissions": _sum_metric(
                        livestock, "gross_emissions_MgCO2e"
                    ),
                }
            )

        summary_rows = [
            {
                "year": row["year"],
                "land_use_emissions": _fold_metric(
                    row["vegetation_emissions"], row["soil_emissions"]
                ),
                "agriculture_emissions": _fold_metric(
                    row["cropland_emissions"], row["livestock_emissions"]
                ),
                "land_use_removals": _fold_metric(
                    row["vegetation_removals"], row["soil_removals"]
                ),
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
            InsightChart(
                position=3,
                title="Net GHG Flux — Annual Average",
                chart_type="hierarchical-bar",
                # A hierarchy has no cartesian axes; each chart_data row's
                # own parent_id pointer carries the tree structure instead
                # (see _hierarchy_rows).
                x_axis="",
                y_axis="",
                chart_data=self._hierarchy_rows(
                    full_rows, category_rows, summary_rows
                ),
            ),
        ]

    @staticmethod
    def _average(rows: List[dict], field: str) -> float | None:
        """Mean of `field` across rows where it's present (not None). None
        (not 0) when the field is never present — a class/category that
        never has this metric (e.g. organic soil has no removals) must not
        fabricate a zero average."""
        values = _metric_values(rows, field)
        return float(np.nanmean(values)) if np.any(~np.isnan(values)) else None

    def _hierarchy_rows(
        self,
        full_rows: List[dict],
        category_rows: List[dict],
        summary_rows: List[dict],
    ) -> List[dict]:
        """The period-of-record-average tree for the annual-average chart:
        one row per node, each carrying its own already-correct
        avg_emissions/avg_removals (not derived by the frontend by summing
        children — every node is independently averaged from the same
        per-year rows the time-series charts already use).

        Depth 3 (leaves) = full_rows fields, depth 2 = category_rows fields,
        depth 1 = summary_rows fields, depth 0 ("All land") is one new root:
        land_use + agriculture summed per year, then averaged — one level
        above what summary_rows computes. category_rows/summary_rows/
        all_land_rows already carry None (not a fabricated 0) wherever a
        field never had a real contributor, so `_average` needs no separate
        presence check — it just averages whatever's there.
        """

        def node(
            id_: str,
            parent_id: str | None,
            label: str,
            emissions_field: str | None,
            removals_field: str | None,
            source_rows: List[dict],
        ) -> dict:
            return {
                "id": id_,
                "parent_id": parent_id,
                "label": label,
                "avg_emissions": (
                    self._average(source_rows, emissions_field)
                    if emissions_field
                    else None
                ),
                "avg_removals": (
                    self._average(source_rows, removals_field)
                    if removals_field
                    else None
                ),
            }

        all_land_rows = [
            {
                "all_land_emissions": _fold_metric(
                    row["land_use_emissions"], row["agriculture_emissions"]
                ),
                "all_land_removals": row["land_use_removals"],
            }
            for row in summary_rows
        ]

        nodes = [
            node(
                "all_land",
                None,
                "All land",
                "all_land_emissions",
                "all_land_removals",
                all_land_rows,
            ),
            node(
                "land_use",
                "all_land",
                "Land use",
                "land_use_emissions",
                "land_use_removals",
                summary_rows,
            ),
            node(
                "agriculture",
                "all_land",
                "Agriculture",
                "agriculture_emissions",
                None,
                summary_rows,
            ),
            node(
                "vegetation",
                "land_use",
                "Vegetation",
                "vegetation_emissions",
                "vegetation_removals",
                category_rows,
            ),
            node(
                "soil",
                "land_use",
                "Soil",
                "soil_emissions",
                "soil_removals",
                category_rows,
            ),
            node(
                "cropland",
                "agriculture",
                "Crop management",
                "cropland_emissions",
                None,
                category_rows,
            ),
            node(
                "livestock",
                "agriculture",
                "Livestock",
                "livestock_emissions",
                None,
                category_rows,
            ),
        ]

        leaf_parent = {
            "tree_loss": "vegetation",
            "tree_gain": "vegetation",
            "trees_remaining_trees": "vegetation",
            "non_trees_remaining_non_trees": "vegetation",
            "mineral_soil": "soil",
            "organic_soil": "soil",
        }
        for class_name, parent_id in leaf_parent.items():
            emissions_field = f"{class_name}_emissions"
            removals_field = f"{class_name}_removals"
            nodes.append(
                node(
                    class_name,
                    parent_id,
                    LGMS_CLASS_LABELS.get(class_name, class_name),
                    emissions_field,
                    removals_field,
                    full_rows,
                )
            )

        return nodes
