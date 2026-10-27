"""Facts: sentences with figures computed in code, for the description.

The text model copies the figures; it does not compute them. A chart
widget's facts read its first chart, whose y axis is an area in hectares.
"""

import math
from typing import Any, Sequence

from src.agent.i18n import t
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.analysis_templates.models import ChartFact
from src.api.services.charts.base import by_area_desc


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


def _values(kind: str, x_axis: str, rows: list[dict]) -> dict:
    """The figures of one fact over rows with an area, largest first."""
    total = math.fsum(row["area_ha"] for row in rows)
    if kind == "total":
        return {"total": hectares(total)}
    # by_area_desc keeps chart order among equal areas: the earlier year.
    top = rows[0]
    values = {
        "category": _label(top[x_axis]),
        "value": hectares(top["area_ha"]),
    }
    if kind == "top_share":
        values |= {
            "share": percent(top["area_ha"], total),
            "total": hectares(total),
        }
    return values


async def chart_facts(
    facts: Sequence[ChartFact],
    chart: InsightChart,
    *,
    aoi_name: str,
    start: str,
    end: str,
    language: str,
) -> list[str]:
    """The facts' sentences in ``language``, in order. With no area, a
    fact gives its empty sentence, or nothing when it has none."""
    if not facts:
        return []
    if chart.y_axis != "area_ha":
        raise ValueError(
            f"Chart facts read areas in hectares, not '{chart.y_axis}'."
        )
    rows = by_area_desc(chart.chart_data)
    common = {
        "aoi_name": aoi_name,
        "start_year": start[:4],
        "end_year": end[:4],
    }
    sentences = []
    for fact in facts:
        if rows:
            values = _values(fact.kind, chart.x_axis, rows)
            sentences.append(
                await t(fact.text_key, language, **common, **values)
            )
        elif fact.empty_key is not None:
            sentences.append(await t(fact.empty_key, language, **common))
    return sentences
