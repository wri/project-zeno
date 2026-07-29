"""Deterministic insight construction for datasets that skip CodeAct.

Some datasets return a nested, per-section result (e.g. Land GHG Inventory's
``{vegetation, agriculture}``) and should render as one table per section with
no LLM call — no CodeAct chart generation and no narrative model. This module
turns such a nested result into ``InsightChart`` tables plus a templated
summary.
"""

from typing import Any

from src.agent.datasets.handlers.analytics_handler import LAND_GHG_INVENTORY_ID
from src.agent.subagents.analyst.charts.model import InsightChart

# Datasets whose generate_insights path is fully deterministic (no LLM).
DETERMINISTIC_DATASETS: set[int] = {LAND_GHG_INVENTORY_ID}


def _is_column_dict(value: Any) -> bool:
    """True when ``value`` is a non-empty column-oriented dict (every value a
    list) — the shape of one nested result section."""
    return (
        isinstance(value, dict)
        and len(value) > 0
        and all(isinstance(col, list) for col in value.values())
    )


def _columns_to_rows(section: dict) -> list[dict]:
    """Transpose a column-oriented section into a list of row dicts."""
    keys = list(section.keys())
    return [dict(zip(keys, values)) for values in zip(*section.values())]


def build_table_insights(result: dict) -> list[InsightChart]:
    """One ``table`` InsightChart per top-level section of a nested result."""
    charts: list[InsightChart] = []
    for section, columns in (result or {}).items():
        if not _is_column_dict(columns):
            continue
        charts.append(
            InsightChart(
                position=len(charts),
                title=str(section).replace("_", " ").title(),
                chart_type="table",
                chart_data=_columns_to_rows(columns),
            )
        )
    return charts


def deterministic_narrative(
    dataset: dict, result: dict
) -> tuple[str, list[str]]:
    """Templated (no-LLM) summary naming the sections, plus empty follow-ups."""
    sections = [
        str(s).replace("_", " ")
        for s, v in (result or {}).items()
        if _is_column_dict(v)
    ]
    name = dataset.get("dataset_name", "Land GHG Inventory")
    if not sections:
        return f"{name}: no tabular data was returned.", []
    return (
        f"{name}: {', '.join(sections)} shown as tables. Emissions are in "
        f"MgCO2e (positive = source); removals are negative (sink).",
        [],
    )
