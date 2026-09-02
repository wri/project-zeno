"""Shared base class and helpers for deterministic chart generators."""

from abc import ABC, abstractmethod
from typing import ClassVar, Iterable, List

import numpy as np

from src.agent.subagents.analyst.charts import InsightChart


def column_to_rows(data: dict) -> List[dict]:
    """Convert column-oriented data ({col: [..]}) to a list of row dicts."""
    keys = list(data.keys())
    return [dict(zip(keys, values)) for values in zip(*data.values())]


def _metric_values(rows: List[dict], field: str) -> np.ndarray:
    """`field` across rows as a float array, None (absent-for-this-row)
    coerced to NaN so numpy's `nan*` reductions skip it."""
    return np.array([r.get(field) for r in rows], dtype=float)


def _sum_metric(rows: List[dict], field: str) -> float | None:
    """Sum of `field` across rows where it's present (not None). None (not 0)
    when no row has it — a class/category that never has this metric must
    not fabricate a zero total; downstream consumers decide how to render
    that absence."""
    values = _metric_values(rows, field)
    return float(np.nansum(values)) if np.any(~np.isnan(values)) else None


def _fold_metric(*values: float | None) -> float | None:
    """Sum values that may be individually None (a sibling category that
    never has this metric), propagating None only when every value is —
    unlike `a + b`, one present side still yields a real total."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def by_area_desc(rows: Iterable[dict]) -> List[dict]:
    """Rows with a positive `area_ha`, largest first."""
    return sorted(
        (row for row in rows if (row.get("area_ha") or 0) > 0),
        key=lambda row: row["area_ha"],
        reverse=True,
    )


class ChartGenerator(ABC):
    """A deterministic chart builder for one dataset.

    Subclasses declare the dataset they serve as a class attribute; the
    dataset is part of the generator's identity, not a runtime choice,
    because each one reads columns only its own dataset returns.
    """

    dataset_id: ClassVar[int]
    # chart_data columns whose values are message keys rather than literals
    # (a chart's category axis is as user-facing as its title).
    label_fields: ClassVar[tuple[str, ...]] = ()

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    @abstractmethod
    def generate(self, rows: List[dict]) -> List[InsightChart]: ...
