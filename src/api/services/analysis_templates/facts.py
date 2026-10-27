"""Facts: sentences with figures computed in code, for the description.

The text model copies the figures; it does not compute them. A chart
widget's facts read its first chart, whose y axis is an area in hectares.
"""

import math
from typing import Any, Optional

from src.agent.i18n import t
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.analysis_templates.models import ChartFact


def hectares(value: float) -> str:
    """Whole hectares, grouped with a narrow no-break space. A comma or a
    point would read as a decimal mark in some languages."""
    if 0 < value < 1:
        return "<1"
    return f"{round(value):,}".replace(",", "\u202f")


def percent(part: float, whole: float) -> str:
    """A whole percent that never rounds a small part to 0% or 100%."""
    share = 100 * part / whole
    if 0 < share < 1:
        return "<1%"
    if 99 < share < 100:
        return ">99%"
    return f"{round(share)}%"


def _label(value: Any) -> str:
    # A year column with a gap arrives as floats: 2021.0 reads as 2021.
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _areas(chart: InsightChart) -> list[tuple[str, float]]:
    """(x value, area) for each row with an area, in chart order."""
    if chart.y_axis != "area_ha":
        raise ValueError(
            f"Chart facts read areas in hectares, not '{chart.y_axis}'."
        )
    return [
        (_label(row[chart.x_axis]), float(row["area_ha"]))
        for row in chart.chart_data
        if row.get("area_ha")
    ]


def _values(kind: str, areas: list[tuple[str, float]]) -> Optional[dict]:
    """The figures of one fact, formatted; None when there is no area."""
    total = math.fsum(area for _, area in areas)
    if total <= 0:
        return None
    if kind == "total":
        return {"total": hectares(total)}
    # The first of equal areas, in chart order: the earlier year.
    category, value = max(areas, key=lambda item: item[1])
    values = {"category": category, "value": hectares(value)}
    if kind == "top_share":
        values |= {"share": percent(value, total), "total": hectares(total)}
    return values


async def chart_fact(
    fact: ChartFact,
    chart: InsightChart,
    *,
    aoi_name: str,
    start: str,
    end: str,
    language: str,
) -> Optional[str]:
    """The fact's sentence in ``language``, its empty sentence when the
    chart has no area, or None when it has no empty sentence."""
    common = {
        "aoi_name": aoi_name,
        "start_year": start[:4],
        "end_year": end[:4],
    }
    values = _values(fact.kind, _areas(chart))
    if values is None:
        if fact.empty_key is None:
            return None
        return await t(fact.empty_key, language, **common)
    return await t(fact.text_key, language, **common, **values)
