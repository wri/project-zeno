"""Canonical in-code chart model — the seam between the chart stage and the
text stage of insight generation.

`InsightChart` carries the chart spec *and* its row data. It is the single typed
object passed between stages and into persistence, and it exposes adapters for
the two wire shapes:

- snake_case for the DB (`InsightChartOrm`) via `to_orm_kwargs()`
- camelCase for the frontend `charts_data` via `to_frontend_dict()`

`Insight` groups the resolved charts with the narrative produced by the
text stage.
"""

import math
from typing import List

from pydantic import BaseModel, Field, field_validator, model_validator

from src.agent.subagents.analyst.code_executors.base import (
    CHART_TYPES_WITHOUT_AXIS,
    ChartInsight,
)


def _json_safe(value):
    """Recursively replace NaN/Inf floats with None.

    `chart_data` rows come from `pandas.DataFrame.to_dict()`, which emits
    `float('nan')` for missing cells. `NaN`/`Infinity` are not valid JSON tokens
    under Postgres' strict `JSONB` parser, so they must be scrubbed before the
    row reaches `to_orm_kwargs()` (DB) or `to_frontend_dict()` (frontend).
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


class InsightChart(BaseModel):
    """A single chart: spec + the rows it renders.

    Mirrors `InsightChartOrm` (snake_case) plus the embedded `chart_data`. The
    optional `insight` field holds the per-chart narrative from the text stage.
    """

    position: int = 0
    title: str
    chart_type: str
    x_axis: str = ""
    y_axis: str = ""
    color_field: str = ""
    stack_field: str = ""
    group_field: str = ""
    series_fields: List[str] = Field(default_factory=list)
    chart_data: List[dict] = Field(default_factory=list)
    insight: str = ""

    @field_validator("chart_data")
    @classmethod
    def sanitize_chart_data(cls, rows: List[dict]) -> List[dict]:
        """Scrub non-finite floats (NaN/Inf) so rows are valid JSONB."""
        return [_json_safe(row) for row in rows]

    @model_validator(mode="after")
    def validate_axis_config(self) -> "InsightChart":
        if self.chart_type not in CHART_TYPES_WITHOUT_AXIS:
            if not self.y_axis and not self.series_fields:
                raise ValueError(
                    f"Chart '{self.title}' (type '{self.chart_type}') is missing axis "
                    "configuration: set 'y_axis' for single-series charts or "
                    "'series_fields' for multi-series charts"
                )
        return self

    # --- adapters -----------------------------------------------------------

    def to_orm_kwargs(self) -> dict:
        """Kwargs for `InsightChartOrm(**...)` (snake_case).

        `insight` is excluded: per-chart narrative is not a chart-row column; it
        lives on the parent `InsightOrm.insight_text`.
        """
        return self.model_dump(exclude={"insight"})

    def to_frontend_dict(self) -> dict:
        """The camelCase shape consumed by the frontend `charts_data`."""
        return {
            "id": f"chart_{self.position}",
            "title": self.title,
            "type": self.chart_type,
            "insight": self.insight,
            "data": self.chart_data,
            "xAxis": self.x_axis,
            "yAxis": self.y_axis,
            "colorField": self.color_field,
            "stackField": self.stack_field,
            "groupField": self.group_field,
            "seriesFields": self.series_fields,
        }

    @classmethod
    def from_chart_insight(
        cls,
        chart: ChartInsight,
        chart_data: List[dict],
        position: int = 0,
    ) -> "InsightChart":
        """Adapt an LLM-produced `ChartInsight` + its rows into the seam model."""
        return cls(
            position=position,
            title=chart.title,
            chart_type=chart.chart_type,
            x_axis=chart.x_axis,
            y_axis=chart.y_axis,
            color_field=chart.color_field,
            stack_field=chart.stack_field,
            group_field=chart.group_field,
            series_fields=chart.series_fields,
            chart_data=chart_data,
        )

    @classmethod
    def from_orm_row(cls, row) -> "InsightChart":
        """Rebuild the seam model from a persisted `InsightChartOrm` row.

        The inverse of `to_orm_kwargs()`: used when an existing insight is
        loaded back from the DB to be restyled (no new data is pulled).
        """
        return cls(
            position=row.position,
            title=row.title,
            chart_type=row.chart_type,
            x_axis=row.x_axis,
            y_axis=row.y_axis,
            color_field=row.color_field,
            stack_field=row.stack_field,
            group_field=row.group_field,
            series_fields=row.series_fields or [],
            chart_data=row.chart_data or [],
        )


class Insight(BaseModel):
    """Resolved charts plus the narrative from the text stage."""

    charts: List[InsightChart]
    primary_insight: str = ""
    follow_up_suggestions: List[str] = Field(default_factory=list)

    def stamp_insight(self) -> "Insight":
        """Copy `primary_insight` onto each chart's `insight` field, so the
        frontend `charts_data` carries the narrative per chart."""
        for chart in self.charts:
            chart.insight = self.primary_insight
        return self
