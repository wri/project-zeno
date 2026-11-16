"""Tree cover loss by dominant driver chart generator."""

import math
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
                # Only the columns that the pie draws. The pull also has
                # the area id, its type and its name, and the emissions.
                chart_data=[
                    {
                        "tree_cover_loss_driver": row[
                            "tree_cover_loss_driver"
                        ],
                        "area_ha": row["area_ha"],
                    }
                    for row in present
                ],
            )
        ]


# The groups of drivers that the dataset's code instructions name
# (src/agent/datasets/catalog/tree_cover_loss_by_dominant_driver.yml).
DRIVER_GROUPS: dict[str, tuple[str, ...]] = {
    "deforestation proxy": (
        "Permanent agriculture",
        "Hard commodities",
        "Settlements and infrastructure",
    ),
    "temporary disturbance": (
        "Shifting cultivation",
        "Logging",
        "Wildfire",
        "Other natural disturbances",
    ),
    "all agriculture": ("Permanent agriculture", "Shifting cultivation"),
}


def driver_facts(rows: List[dict]) -> List[str]:
    """Facts that the pie cannot give, as sentences for a model to copy:
    the area of the Unknown driver and the total with it, and the area of
    each group of drivers with its percent of the loss with a known
    driver. [] when no row has an area."""
    # Lazy: the charts package init imports this module through the
    # generator registry.
    from src.api.services.charts.facts import number

    areas: dict[str, float] = {}
    for row in rows:
        area = row.get("area_ha")
        if area is None:
            continue
        key = _fold(row.get("tree_cover_loss_driver") or "")
        areas[key] = areas.get(key, 0.0) + float(area)
    unknown = areas.pop(_fold(UNKNOWN_DRIVER), 0.0)
    known = math.fsum(areas.values())
    if not known and not unknown:
        return []
    facts = [
        f"Unknown driver, not in the chart: {number(unknown)} ha.",
        f"Total loss with the Unknown driver: {number(known + unknown)} ha.",
    ]
    for group, members in DRIVER_GROUPS.items():
        area = math.fsum(areas.get(_fold(m), 0.0) for m in members)
        share = (
            f", {number(100 * area / known)}% of the loss with a known driver"
            if known
            else ""
        )
        facts.append(
            f"Group {group} ({', '.join(m.lower() for m in members)}): "
            f"{number(area)} ha{share}."
        )
    return facts
