"""Deterministic chart generators — rule/config-driven builders that turn
pulled data into `InsightChart`s without calling an LLM.

`AnalyzeService` is injected with a sequence of these and picks the first whose
`can_handle(dataset_id)` matches; datasets with no matching generator yield no
charts.
"""

from abc import ABC, abstractmethod
from collections import defaultdict
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


def _sum_metric(rows: List[dict], field: str) -> float:
    """Sum of `field` across rows, treating None (absent-for-this-row) as no
    contribution rather than 0 by coincidence of falsiness."""
    return sum(r[field] for r in rows if r.get(field) is not None)


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
            InsightChart(
                position=3,
                title="Net GHG Flux — Annual Average",
                chart_type="hierarchical-bar",
                # A hierarchy has no cartesian axes; chart_data's own
                # parent_id pointers carry the structure (see
                # _hierarchy_rows and project-zeno-next's
                # src/features/ghg-flux-tree, which is the sole consumer of
                # this chart_type and owns the id/parent_id/label/
                # avg_emissions/avg_removals field contract).
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
        present = [r for r in rows if r.get(field) is not None]
        return _sum_metric(present, field) / len(present) if present else None

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
        above what summary_rows computes.
        """

        vegetation_classes = (
            "tree_loss",
            "tree_gain",
            "trees_remaining_trees",
            "non_trees_remaining_non_trees",
        )
        soil_classes = ("mineral_soil", "organic_soil")

        # Every field this chart can average, mapped to the full_rows leaf
        # keys it folds — the only place None-vs-0 presence survives, since
        # category_rows/summary_rows/all_land_rows always carry every key
        # (0.0 when nothing contributed). A field backed by no present leaf
        # is never even passed to _average, rather than risking it average an
        # always-populated 0.0 into a fabricated value.
        backing_leaves = {
            "vegetation_emissions": [
                f"{c}_emissions" for c in vegetation_classes
            ],
            "vegetation_removals": [
                f"{c}_removals" for c in vegetation_classes
            ],
            "soil_emissions": [f"{c}_emissions" for c in soil_classes],
            "soil_removals": [f"{c}_removals" for c in soil_classes],
            "cropland_emissions": ["cropland_emissions"],
            "livestock_emissions": ["livestock_emissions"],
        }
        backing_leaves["land_use_emissions"] = (
            backing_leaves["vegetation_emissions"]
            + backing_leaves["soil_emissions"]
        )
        backing_leaves["land_use_removals"] = (
            backing_leaves["vegetation_removals"]
            + backing_leaves["soil_removals"]
        )
        backing_leaves["agriculture_emissions"] = (
            backing_leaves["cropland_emissions"]
            + backing_leaves["livestock_emissions"]
        )
        backing_leaves["all_land_emissions"] = (
            backing_leaves["land_use_emissions"]
            + backing_leaves["agriculture_emissions"]
        )
        backing_leaves["all_land_removals"] = backing_leaves[
            "land_use_removals"
        ]

        def is_backed(field: str) -> bool:
            return any(
                leaf in row
                for row in full_rows
                for leaf in backing_leaves[field]
            )

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
                    if emissions_field and is_backed(emissions_field)
                    else None
                ),
                "avg_removals": (
                    self._average(source_rows, removals_field)
                    if removals_field and is_backed(removals_field)
                    else None
                ),
            }

        all_land_rows = [
            {
                "all_land_emissions": row["land_use_emissions"]
                + row["agriculture_emissions"],
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
            backing_leaves[emissions_field] = [emissions_field]
            backing_leaves[removals_field] = [removals_field]
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


DETERMINISTIC_GENERATORS: List[ChartGenerator] = [
    TCLChartGenerator(),
    IntegratedAlertsChartGenerator(),
    LGMSChartGenerator(),
]
