"""Tree cover loss by dominant driver chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_BY_DRIVER_ID,
)
from src.agent.datasets.palette import PALETTES
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator, by_area_desc
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

UNKNOWN_DRIVER = "Unknown"


def _fold(label: str) -> str:
    """The analytics API spells one class two ways: "Settlements and
    infrastructure" in its precalculated admin results and "Settlements &
    Infrastructure" for other areas, as the catalog does. Folding the
    ampersand, case and spacing joins both to the catalog label."""
    return " ".join(label.replace("&", " and ").split()).casefold()


# Each slice takes the colour of its driver on the driver map layer.
DRIVER_COLORS = {
    _fold(category["label_en"]): category["color"]
    for category in PALETTES[TREE_COVER_LOSS_BY_DRIVER_ID]["categories"]
}


def _color_map(rows: List[dict]) -> dict[str, str]:
    """The colour of each driver, keyed by its label in the data."""
    colors = {}
    for row in rows:
        label = row["tree_cover_loss_driver"]
        color = DRIVER_COLORS.get(_fold(label))
        if color is None:
            # The frontend gives the slice a theme colour instead.
            logger.warning("tcl_driver_has_no_color", driver=label)
            continue
        colors[label] = color
    return colors


class TCLByDriverChartGenerator(ChartGenerator):
    """Tree cover loss area per driver as a pie, excluding unknown drivers."""

    dataset_id = TREE_COVER_LOSS_BY_DRIVER_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = by_area_desc(
            row
            for row in rows
            if row.get("tree_cover_loss_driver") != UNKNOWN_DRIVER
        )
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="charts.tcl_by_driver.by_driver",
                chart_type="pie",
                x_axis="tree_cover_loss_driver",
                y_axis="area_ha",
                color_map=_color_map(present),
                chart_data=present,
            )
        ]
