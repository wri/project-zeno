"""Deterministic chart generation — rule/config-driven builders that turn
pulled data into `InsightChart`s without calling an LLM.

One `ChartGenerator` exists per dataset; `registry.py` owns the
dataset-id → generator mapping that `AnalyzeService` consults.
"""

from abc import ABC, abstractmethod
from typing import List

from src.agent.subagents.analyst.charts import InsightChart


def column_to_rows(data: dict) -> List[dict]:
    """Convert column-oriented data ({col: [..]}) to a list of row dicts."""
    keys = list(data.keys())
    return [dict(zip(keys, values)) for values in zip(*data.values())]


class ChartGenerator(ABC):
    """A deterministic chart builder for one dataset."""

    @abstractmethod
    def generate(self, rows: List[dict]) -> List[InsightChart]: ...
