"""Facts: figures computed in code from a curated chart.

A model copies the figures; it does not compute them. Two users:

- The analysis templates (`ChartFact`, `chart_facts`): localised sentences
  for the description of a section, from a chart whose y axis is an area
  in hectares.
- The agent (`Fact`, `measure_facts`): structured values and English
  sentences for the tool message of a curated chart, for each measure of
  the chart and its unit (docs/curated-charts-first-plan.md, section 4).
"""

import math
from dataclasses import dataclass
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict

from src.agent.i18n import t
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import by_area_desc
from src.api.services.charts.gate import measures


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


# The unit of a value column. A column that is not here gets its unit from
# its name (`unit_of`).
UNITS = {
    "area_ha": "ha",
    "carbon_emissions_MgCO2e": "MgCO2e",
}


def unit_of(column: str) -> str:
    """The unit of a value column; "" when the name does not tell."""
    if column in UNITS:
        return UNITS[column]
    lowered = column.lower()
    if lowered.endswith("_ha") or lowered == "ha":
        return "ha"
    for unit in ("MgCO2e", "tCO2e"):
        if unit.lower() in lowered:
            return unit
    if lowered.endswith(("_pct", "_percent")):
        return "%"
    return ""


def number(value: float) -> str:
    """A figure for a model to copy: a whole number as it is, else two
    decimals, and four significant digits below 1. No group separators."""
    if isinstance(value, int) or (
        isinstance(value, float) and value.is_integer()
    ):
        return str(int(value))
    if abs(value) < 1:
        return f"{value:.4g}"
    return f"{value:.2f}"


def _with_unit(value: float, unit: str) -> str:
    if unit == "%":
        return f"{number(value)}%"
    return f"{number(value)} {unit}".rstrip()


def _signed(value: float, unit: str) -> str:
    text = _with_unit(value, unit)
    return text if value < 0 else f"+{text}"


def is_time_axis(chart: InsightChart) -> bool:
    """True when the x axis of the chart is a year, a month or a date."""
    name = chart.x_axis.lower()
    if any(part in name for part in ("year", "date", "month")):
        return True
    values = [row.get(chart.x_axis) for row in chart.chart_data]
    return bool(values) and all(
        isinstance(v, (int, float))
        and float(v).is_integer()
        and 1900 <= v <= 2100
        for v in values
    )


@dataclass(frozen=True)
class Fact:
    """One figure of a chart, computed in code.

    total: the sum of `measure`, over `x` to `x_to`. max, min: the largest
    and the smallest value, at `x`. change: the last value less the first
    one, from `x` to `x_to`, with `share` as the change in percent of the
    size of the first value (None when the first value is 0). rank: the value of the
    class `x`, at position `rank` (1 is the largest), with `share` as its
    percent of the total.
    """

    kind: Literal["total", "max", "min", "change", "rank"]
    measure: str
    unit: str
    value: float
    x: Optional[str] = None
    x_to: Optional[str] = None
    share: Optional[float] = None
    rank: Optional[int] = None

    @property
    def sentence(self) -> str:
        value = _with_unit(self.value, self.unit)
        if self.kind == "total":
            span = f" from {self.x} to {self.x_to}" if self.x_to else ""
            return f"Total {self.measure}{span}: {value}."
        if self.kind == "max":
            return f"Largest {self.measure}: {value} in {self.x}."
        if self.kind == "min":
            return f"Smallest {self.measure}: {value} in {self.x}."
        if self.kind == "change":
            percent = (
                f" ({_signed(self.share, '%')})"
                if self.share is not None
                else ""
            )
            return (
                f"Change of {self.measure} from {self.x} to {self.x_to}: "
                f"{_signed(self.value, self.unit)}{percent}."
            )
        share = (
            f", {number(self.share)}% of the total"
            if self.share is not None
            else ""
        )
        return f"Rank {self.rank} of {self.measure}: {self.x}, {value}{share}."


def _points(chart: InsightChart, measure: str) -> list[tuple[str, float]]:
    """(x label, value) for each row with a value, in chart order."""
    return [
        (_label(row.get(chart.x_axis)), float(row[measure]))
        for row in chart.chart_data
        if row.get(measure) is not None
    ]


def _series_facts(
    measure: str, unit: str, points: list[tuple[str, float]], time: bool
) -> list[Fact]:
    total = math.fsum(value for _, value in points)
    if time:
        # Chart order is time order; max and min keep the earlier x of a tie.
        first, last = points[0], points[-1]
        largest = max(points, key=lambda point: point[1])
        smallest = min(points, key=lambda point: point[1])
        facts = [
            Fact("total", measure, unit, total, first[0], last[0]),
            Fact("max", measure, unit, largest[1], largest[0]),
            Fact("min", measure, unit, smallest[1], smallest[0]),
        ]
        if len(points) > 1:
            change = last[1] - first[1]
            facts.append(
                Fact(
                    "change",
                    measure,
                    unit,
                    change,
                    first[0],
                    last[0],
                    # Of the size of the first value: a rise from -10 to
                    # -5 is +50%, not -50%.
                    share=(100 * change / abs(first[1]) if first[1] else None),
                )
            )
        return facts
    facts = [Fact("total", measure, unit, total)]
    # A share is a part of a whole only when no value is negative.
    shares = total > 0 and all(value >= 0 for _, value in points)
    ranked = sorted(points, key=lambda point: point[1], reverse=True)
    for position, (x, value) in enumerate(ranked, 1):
        facts.append(
            Fact(
                "rank",
                measure,
                unit,
                value,
                x,
                share=100 * value / total if shares else None,
                rank=position,
            )
        )
    return facts


def measure_facts(chart: InsightChart) -> list[Fact]:
    """The facts of each measure of a chart: for a time axis the total,
    the largest and the smallest value with their x, and the change from
    the first to the last x; for classes the total and each class by rank
    with its share. A stacked chart also gets the total of all its series
    when they have one unit."""
    time = is_time_axis(chart)
    columns = measures(chart)

    def unit(measure: str) -> str:
        # A series with a display name ("Highest confidence") has no unit
        # in its name: the unit of the chart's y axis applies.
        return unit_of(measure) or unit_of(chart.y_axis)

    facts: list[Fact] = []
    for measure in columns:
        points = _points(chart, measure)
        if points:
            facts.extend(_series_facts(measure, unit(measure), points, time))
    units = {unit(measure) for measure in columns}
    if len(columns) > 1 and len(units) == 1:
        values = [
            float(row[measure])
            for row in chart.chart_data
            for measure in columns
            if row.get(measure) is not None
        ]
        if values:
            facts.append(
                Fact("total", "all series", units.pop(), math.fsum(values))
            )
    return facts
