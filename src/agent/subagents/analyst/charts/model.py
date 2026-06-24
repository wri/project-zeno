"""Canonical in-code chart model — the seam between the chart stage and the
text stage of insight generation.

`InsightChart` carries the chart spec *and* its row data. It is the single typed
object passed between stages and into persistence, and it exposes adapters for
the two wire shapes:

- snake_case for the DB (`InsightChartOrm`) via `to_orm_kwargs()`
- camelCase for the frontend `charts_data` via `to_frontend_dict()` /
  `from_frontend_dict()`

`InsightBundle` groups the resolved charts with the narrative produced by the
text stage.
"""

from typing import List

from pydantic import BaseModel, Field, model_validator

from src.agent.subagents.analyst.code_executors.base import (
    CHART_TYPES_WITHOUT_AXIS,
    ChartInsight,
)


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
    def from_frontend_dict(
        cls, data: dict, position: int = 0
    ) -> "InsightChart":
        """Inverse of `to_frontend_dict()` — rehydrate a chart already in state.

        `id` is derived from `position` on the way out, so it is not read back
        here; the caller supplies `position` (defaulting to the list index).
        """
        return cls(
            position=position,
            title=data.get("title", ""),
            chart_type=data.get("type", "bar"),
            x_axis=data.get("xAxis", ""),
            y_axis=data.get("yAxis", ""),
            color_field=data.get("colorField", ""),
            stack_field=data.get("stackField", ""),
            group_field=data.get("groupField", ""),
            series_fields=data.get("seriesFields", []),
            chart_data=data.get("data", []),
            insight=data.get("insight", ""),
        )

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


class InsightBundle(BaseModel):
    """Resolved charts plus the narrative from the text stage."""

    charts: List[InsightChart]
    primary_insight: str = ""
    follow_up_suggestions: List[str] = Field(default_factory=list)

    def stamp_insight(self) -> "InsightBundle":
        """Copy `primary_insight` onto each chart's `insight` field, so the
        frontend `charts_data` carries the narrative per chart."""
        for chart in self.charts:
            chart.insight = self.primary_insight
        return self
