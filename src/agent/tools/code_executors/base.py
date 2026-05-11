"""Base classes and types for code executors."""

from base64 import b64encode
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


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
        description="Name of the field to use for Y-axis (for applicable chart types)"
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
        description="List of field names for multiple data series (for multi-bar charts)",
    )


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
