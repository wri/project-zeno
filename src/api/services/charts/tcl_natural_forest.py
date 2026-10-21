"""Tree cover loss split into SBTN natural forest and other tree cover."""

from typing import Iterable, List

from src.agent.datasets.handlers.analytics_handler import (
    NATURAL_LANDS_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.datasets.palette import PALETTES
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

# The SBTN Natural Lands Map is a 2020 baseline, so the split covers loss
# from 2021 on. The analytics API rejects an earlier start.
FIRST_YEAR = 2021

# The columns of a split row, in ha.
NATURAL_COLUMN = "natural_forest_area_ha"
OTHER_COLUMN = "other_tree_cover_area_ha"
# The two pulls sum the same pixels, natural forest a subset of them, but
# two float sums can differ in their last digits.
_RELATIVE_TOLERANCE = 1e-6

NATURAL_SERIES = "charts.label.natural_forest"
OTHER_SERIES = "charts.label.other_tree_cover"
# Natural forest takes the colour of the natural forest map layer, other
# tree cover the colour of the tree cover loss layer.
_NATURAL_FOREST_COLOR = next(
    category["color"]
    for category in PALETTES[NATURAL_LANDS_ID]["categories"]
    if category["slug"] == "natural_forests"
)
_TREE_COVER_LOSS_COLOR = PALETTES[TREE_COVER_LOSS_ID]["series_color"]
assert _TREE_COVER_LOSS_COLOR is not None
SERIES_COLORS = {
    NATURAL_SERIES: _NATURAL_FOREST_COLOR,
    OTHER_SERIES: _TREE_COVER_LOSS_COLOR,
}


def _area_by_year(rows: Iterable[dict]) -> dict[int, float]:
    totals: dict[int, float] = {}
    for row in rows:
        year = int(row["tree_cover_loss_year"])
        totals[year] = totals.get(year, 0.0) + (row.get("area_ha") or 0.0)
    return totals


def split_by_year(
    natural_rows: Iterable[dict], all_rows: Iterable[dict]
) -> List[dict]:
    """One row per year with loss in natural forest and in other tree
    cover, in ha, from two tree cover loss pulls at the same canopy
    threshold: one in natural forest, one of all tree cover.

    Other tree cover is all loss minus natural forest loss: plantations and
    tree crops, and loss outside the 2020 forest classes. More natural
    forest loss than all loss raises, as the two pulls do not match.
    """
    natural = _area_by_year(natural_rows)
    total = _area_by_year(all_rows)
    rows = []
    for year in sorted(natural.keys() | total.keys()):
        natural_ha, total_ha = natural.get(year, 0.0), total.get(year, 0.0)
        if natural_ha - total_ha > _RELATIVE_TOLERANCE * max(total_ha, 1.0):
            raise ValueError(
                f"Natural forest loss in {year} ({natural_ha} ha) is more "
                f"than all tree cover loss ({total_ha} ha)."
            )
        rows.append(
            {
                "tree_cover_loss_year": year,
                NATURAL_COLUMN: natural_ha,
                OTHER_COLUMN: max(total_ha - natural_ha, 0.0),
            }
        )
    return rows


def natural_forest_totals(rows: Iterable[dict]) -> tuple[float, float]:
    """Natural forest loss and all loss in ha, over the split rows."""
    natural = other = 0.0
    for row in rows:
        natural += row[NATURAL_COLUMN]
        other += row[OTHER_COLUMN]
    return natural, natural + other


class TCLNaturalForestChartGenerator(ChartGenerator):
    """Tree cover loss per year as a stacked bar: other tree cover at the
    bottom, natural forest on top.

    It reads the rows of ``split_by_year``, which only the analysis
    templates make, so it is not in DETERMINISTIC_GENERATORS: a tree cover
    loss pull keeps its default chart. Every year of the range gets a row,
    zero when there was no loss, so the bars line up.
    """

    dataset_id = TREE_COVER_LOSS_ID
    label_series = True

    def __init__(self, start_year: int, end_year: int):
        self._years = range(start_year, end_year + 1)

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        by_year = {row["tree_cover_loss_year"]: row for row in rows}
        chart_data = []
        for year in sorted(set(self._years) | set(by_year)):
            row = by_year.get(year, {})
            chart_data.append(
                {
                    "tree_cover_loss_year": year,
                    OTHER_SERIES: row.get(OTHER_COLUMN, 0.0),
                    NATURAL_SERIES: row.get(NATURAL_COLUMN, 0.0),
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
