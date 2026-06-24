"""Chart layer for the analyst: the canonical `InsightChart`/`InsightBundle`
seam model shared by both insight paths."""

from src.agent.subagents.analyst.charts.model import (
    InsightBundle,
    InsightChart,
)

__all__ = [
    "InsightBundle",
    "InsightChart",
]
