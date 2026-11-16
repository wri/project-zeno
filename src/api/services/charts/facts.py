"""Facts: sentences with figures computed in code from a curated chart.

A text model copies the figures; it does not compute them. The analysis
templates use the facts for the description of a section. A fact reads one
chart, whose y axis is an area in hectares.
"""

import math
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict

from src.agent.i18n import t
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import by_area_desc


class ChartFact(BaseModel):
    """A sentence with a figure from a chart widget's first chart, computed
    in code (``facts``), that the description must give."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # total: the sum of the areas, as {total}. peak: the x value with the
    # largest area, as {category}, and that area, as {value}. top_share: the
    # same, plus its share of the sum, as {share}, and the sum, as {total}.
    kind: Literal["total", "peak", "top_share"]
    # i18n key of the sentence. It can also use {aoi_name}, {start_year}
    # and {end_year}.
    text_key: str
    # i18n key of the sentence when the chart has no area, with those three
    # placeholders only. None leaves the fact out.
    empty_key: Optional[str] = None


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
