"""Tree cover loss split into SBTN natural forest and other tree cover."""

from typing import Iterable, List

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_LOSS_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

# The SBTN Natural Lands Map is a 2020 baseline, so the split covers loss
# from 2021 on. The analytics API rejects an earlier start.
FIRST_YEAR = 2021

CLASS_COLUMN = "natural_forests_class"
NATURAL_FOREST_CLASS = "Natural Forest"
# Plantations and tree crops, and loss outside the 2020 forest classes.
OTHER_CLASSES = ("Non-natural Forest", "Unknown")

NATURAL_SERIES = "charts.label.natural_forest"
OTHER_SERIES = "charts.label.other_tree_cover"
# Natural forest takes the green of the natural forest map layer, other
# tree cover the pink of the tree cover loss layer.
SERIES_COLORS = {NATURAL_SERIES: "#246E24", OTHER_SERIES: "#DC6C9A"}


def split_by_year(rows: Iterable[dict]) -> dict[int, tuple[float, float]]:
    """Natural forest loss and other loss in ha, by year.

    A row with no class or another class raises: a new class from the
    analytics API must not pass as other tree cover.
    """
    split: dict[int, list[float]] = {}
    for row in rows:
        forest_class = row.get(CLASS_COLUMN)
        if forest_class == NATURAL_FOREST_CLASS:
            index = 0
        elif forest_class in OTHER_CLASSES:
            index = 1
        else:
            raise ValueError(f"Unknown natural forest class: {forest_class!r}")
        totals = split.setdefault(int(row["tree_cover_loss_year"]), [0.0, 0.0])
        totals[index] += row.get("area_ha") or 0.0
    return {year: (natural, other) for year, (natural, other) in split.items()}


def natural_forest_totals(rows: Iterable[dict]) -> tuple[float, float]:
    """Natural forest loss and all loss in ha, over every row."""
    split = split_by_year(rows).values()
    natural = sum(natural for natural, _ in split)
    return natural, natural + sum(other for _, other in split)


class TCLNaturalForestChartGenerator(ChartGenerator):
    """Tree cover loss per year as a stacked bar: other tree cover at the
    bottom, natural forest on top.

    It reads the rows of the natural forest breakdown, which only the
    analysis templates request, so it is not in DETERMINISTIC_GENERATORS:
    a tree cover loss pull keeps its default chart. Every year of the range
    gets a row, zero when there was no loss, so the bars line up.
    """

    dataset_id = TREE_COVER_LOSS_ID
    label_series = True

    def __init__(self, start_year: int, end_year: int):
        self._years = range(start_year, end_year + 1)

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        split = split_by_year(rows)
        chart_data = []
        for year in sorted(set(self._years) | set(split)):
            natural, other = split.get(year, (0.0, 0.0))
            chart_data.append(
                {
                    "tree_cover_loss_year": year,
                    OTHER_SERIES: other,
                    NATURAL_SERIES: natural,
                }
            )
        return [
            InsightChart(
                position=0,
                title="charts.tcl_natural_forest.annual_split",
                chart_type="stacked-bar",
                x_axis="tree_cover_loss_year",
                # Only the axis title: the series fields name the bars.
                y_axis="area_ha",
                # The first series is the bottom of the stack.
                series_fields=[OTHER_SERIES, NATURAL_SERIES],
                color_map=dict(SERIES_COLORS),
                chart_data=chart_data,
            )
        ]
