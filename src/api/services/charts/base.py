"""Deterministic chart generation — rule/config-driven builders that turn
pulled data into `InsightChart`s without calling an LLM.

One `ChartGenerator` exists per dataset; `registry.py` owns the
dataset-id → generator mapping that `AnalyzeService` consults.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from src.agent.subagents.analyst.charts import InsightChart


def column_to_rows(data: dict) -> List[dict]:
    """Convert column-oriented data ({col: [..]}) to a list of row dicts.

    The analytics API can return ragged columns (e.g. grasslands returns a
    shorter aoi_type column than its year/area_ha columns), so rows are
    built to the longest column with missing cells as None — zipping would
    silently truncate data rows to the shortest metadata column.
    """
    length = max((len(values) for values in data.values()), default=0)
    return [
        {
            key: (values[i] if i < len(values) else None)
            for key, values in data.items()
        }
        for i in range(length)
    ]


def drop_zero_rows(rows: List[dict], column: str) -> List[dict]:
    """Drop rows whose ``column`` is zero or missing."""
    return [row for row in rows if (row.get(column) or 0) != 0]


def sort_rows(rows: List[dict], column: str) -> List[dict]:
    """Sort rows by ``column``. The analytics API returns rows in arbitrary
    order, so every axis-ordered chart must sort explicitly."""
    return sorted(rows, key=lambda row: row[column])


def group_sum(
    rows: List[dict], key_column: str, value_column: str
) -> List[dict]:
    """Sum ``value_column`` per ``key_column`` value, sorted descending by
    total. Also collapses rows from multi-AOI requests into one row per
    key."""
    totals: dict = {}
    for row in rows:
        key = row.get(key_column)
        totals[key] = totals.get(key, 0.0) + (row.get(value_column) or 0.0)
    return [
        {key_column: key, value_column: value}
        for key, value in sorted(
            totals.items(), key=lambda item: item[1], reverse=True
        )
    ]


def monthly_totals(
    rows: List[dict],
    date_column: str,
    value_column: str,
    group_column: Optional[str] = None,
) -> List[dict]:
    """Aggregate daily rows into calendar-month totals, sorted by month.

    Without ``group_column``: one row per month, ``{"month", value_column}``.
    With ``group_column``: wide rows with one column per group value, missing
    months filled with 0.0 — the frontend renders multi-series charts from
    ``series_fields`` columns, so long-format group rows are not usable.
    """
    if group_column is None:
        totals: dict[str, float] = {}
        for row in rows:
            month = str(row.get(date_column, ""))[:7]
            totals[month] = totals.get(month, 0.0) + (
                row.get(value_column) or 0.0
            )
        return [
            {"month": month, value_column: value}
            for month, value in sorted(totals.items())
        ]

    grouped: dict[tuple[str, str], float] = {}
    for row in rows:
        month = str(row.get(date_column, ""))[:7]
        group = str(row.get(group_column, ""))
        grouped[(month, group)] = grouped.get((month, group), 0.0) + (
            row.get(value_column) or 0.0
        )
    months = sorted({month for month, _ in grouped})
    groups = sorted({group for _, group in grouped})
    return [
        {
            "month": month,
            **{group: grouped.get((month, group), 0.0) for group in groups},
        }
        for month in months
    ]


class ChartGenerator(ABC):
    """A deterministic chart builder for one dataset."""

    @abstractmethod
    def generate(self, rows: List[dict]) -> List[InsightChart]: ...
