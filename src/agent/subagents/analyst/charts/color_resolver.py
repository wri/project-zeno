"""Deterministic color resolution for `InsightChart` (phase 2).

Attaches `color_map` / `series_color` / `divergent_colors` onto a chart from
the backend color registry (`src/agent/datasets/palette.py`), keyed by
`dataset_id` plus the stable English slug the code-executor emits alongside a
chart's categorical grouping column — see docs/insight-chart-colors-plan.md,
decisions 2 and 5.

This is a plain, deterministic post-processing step: it never asks an LLM to
invent colors. A category slug with no registry entry (e.g. an LLM-invented
grouped bucket like "Agriculture") gets a deterministic fallback color, hashed
from the slug so the same slug always gets the same color across
regenerations of the same insight.
"""

import hashlib
from typing import Optional

from src.agent.datasets.palette import get_dataset_palette

# The code-executor emits this sibling column next to any categorical column
# used for chart coloring, e.g. "driver__slug" next to "driver".
SLUG_COLUMN_SUFFIX = "__slug"

# Fallback palette for slugs with no registry entry. Order is irrelevant — the
# pick is a hash of the slug, not a position.
_FALLBACK_PALETTE = [
    "#4C78A8",
    "#F58518",
    "#54A24B",
    "#B279A2",
    "#E45756",
    "#72B7B2",
    "#EECA3B",
    "#FF9DA6",
    "#9D755D",
    "#BAB0AC",
]


def _fallback_color(slug: str) -> str:
    digest = hashlib.sha256(slug.encode("utf-8")).digest()
    return _FALLBACK_PALETTE[digest[0] % len(_FALLBACK_PALETTE)]


def _categorical_column(chart) -> str:
    """The chart_data column whose values drive per-category coloring, if any.

    Bar/line/area/scatter/grouped-bar/stacked-bar use `color_field` when set.
    Pie charts group by their category column, which the code executor always
    puts in `x_axis` (pie has no `color_field`).
    """
    if chart.color_field:
        return chart.color_field
    if chart.chart_type == "pie":
        return chart.x_axis
    return ""


def resolve_chart_colors(chart, dataset_id: Optional[int]):
    """Return `chart` with `dataset_id`/`color_map`/`series_color`/
    `divergent_colors` attached from the registry. Mutates and returns
    `chart` in place; `chart_data` and field mappings are untouched.
    """
    chart.dataset_id = dataset_id
    palette = (
        get_dataset_palette(dataset_id) if dataset_id is not None else None
    )
    if palette is None:
        chart.color_map = {}
        chart.series_color = None
        chart.divergent_colors = None
        return chart

    column = _categorical_column(chart)
    if column:
        slug_column = f"{column}{SLUG_COLUMN_SUFFIX}"
        registry_colors = {
            category["slug"]: category["color"]
            for category in palette["categories"]
        }
        slugs: set[str] = set()
        for row in chart.chart_data:
            value = row.get(slug_column, row.get(column))
            if value is not None:
                slugs.add(str(value))
        chart.color_map = {
            slug: registry_colors.get(slug) or _fallback_color(slug)
            for slug in slugs
        }
    else:
        chart.color_map = {}

    chart.series_color = palette["series_color"]
    chart.divergent_colors = (
        dict(palette["divergent_colors"])
        if palette["divergent_colors"] is not None
        else None
    )
    return chart
