"""Base classes and types for code executors."""

from abc import ABC, abstractmethod
from base64 import b64encode
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from pydantic import BaseModel, Field, model_validator

CHART_TYPES_WITHOUT_AXIS = {"pie", "table"}


class ChartInsight(BaseModel):
    """
    Represents a chart-based insight with Recharts-compatible data.
    """

    title: str = Field(description="Clear, descriptive title for the chart")
    chart_type: str = Field(
        description="Chart type: 'line', 'bar', 'stacked-bar', 'grouped-bar', 'pie', 'area', 'scatter', or 'table'"
    )
    x_axis: str = Field(
        description="Name of the field to use for X-axis (for applicable chart types)"
    )
    y_axis: str = Field(
        default="",
        description="Name of the field to use for Y-axis. Required for single-series charts. Leave empty for multi-series charts and populate series_fields instead.",
    )
    color_field: str = Field(
        default="",
        description="Optional field name for color grouping/categorization",
    )
    stack_field: str = Field(
        default="",
        description="Field name for stacking data (for stacked-bar charts)",
    )
    group_field: str = Field(
        default="",
        description="Field name for grouping bars (for grouped-bar charts)",
    )
    series_fields: List[str] = Field(
        default=[],
        description="List of field names for multiple data series (for multi-series charts). Required when y_axis is empty.",
    )

    @model_validator(mode="after")
    def validate_axis_config(self) -> "ChartInsight":
        if self.chart_type not in CHART_TYPES_WITHOUT_AXIS:
            if not self.y_axis and not self.series_fields:
                raise ValueError(
                    f"Chart '{self.title}' (type '{self.chart_type}') is missing axis "
                    "configuration: set 'y_axis' for single-series charts or "
                    "'series_fields' for multi-series charts"
                )
        return self


class MultiChartInsight(BaseModel):
    """
    Represents multiple chart-based insights from a single analysis.
    Used when the data supports multiple visualizations (e.g., tree cover loss AND emissions).
    """

    charts: List[ChartInsight] = Field(
        min_length=1,
        max_length=2,
        description="List of 1-2 charts to display, each with title, type, and field mappings",
    )
    primary_insight: str = Field(
        description="Overall insight that ties all charts together (2-3 sentences)"
    )
    follow_up_suggestions: List[str] = Field(
        description="List of 1-2 follow-up suggestions based on available data and capability"
    )


class PartType(Enum):
    TEXT_OUTPUT = "text_output"
    CODE_BLOCK = "code_block"
    EXECUTION_OUTPUT = "execution_output"


class CodeActPart(BaseModel):
    type: PartType
    content: str


@dataclass
class ExecutionResult:
    """Result from code execution."""

    parts: List[CodeActPart]
    chart_data: Optional[List[Dict]]
    insight: Optional[MultiChartInsight]

    error: Optional[str] = None

    def get_encoded_parts(self) -> List[Dict]:
        return [
            {
                "type": part.type.value,
                "content": b64encode(part.content.encode("utf-8")).decode(
                    "utf-8"
                ),
            }
            for part in self.parts
        ]


class CodeExecutor(ABC):
    """Interface every code executor must implement.

    The analyst (`generate_insights`) drives any executor through three calls:
    `build_file_references` (prompt text describing the data), then
    `prepare_dataframes` (executor-specific payload), then `execute`. Each
    executor also exposes a `workflow` string so the analyst can inject the
    matching step-by-step instructions into the prompt (file-based vs
    variable-based).
    """

    #: Step-by-step workflow text injected into the analysis prompt.
    workflow: str = ""

    @abstractmethod
    def build_file_references(
        self, dataframes: List[Tuple[pd.DataFrame, str]]
    ) -> str:
        """Return the prompt section describing the available data."""

    @abstractmethod
    async def prepare_dataframes(
        self, dataframes: List[Tuple[pd.DataFrame, str]]
    ) -> Any:
        """Convert dataframes into the executor-specific payload."""

    @abstractmethod
    async def execute(self, prompt: str, prepared: Any) -> ExecutionResult:
        """Run the analysis and return an ExecutionResult."""
