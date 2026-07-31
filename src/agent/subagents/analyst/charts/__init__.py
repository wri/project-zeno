"""Chart layer for the analyst: the canonical `InsightChart`/`Insight`
seam model shared by both insight paths."""

from src.agent.subagents.analyst.charts.color_resolver import (
    resolve_chart_colors,
)
from src.agent.subagents.analyst.charts.model import (
    Insight,
    InsightChart,
)

__all__ = [
    "Insight",
    "InsightChart",
    "resolve_chart_colors",
]
