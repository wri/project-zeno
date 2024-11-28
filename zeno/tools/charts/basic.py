import base64
import io
from typing import List, Optional

import matplotlib.pyplot as plt
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# Switch to non-interactive backend
plt.switch_backend("Agg")


class BarChartInput(BaseModel):
    """Input schema for bar chart creator tool"""

    data: List[float] = Field(
        description="List of numerical values to plot in the bar chart"
    )
    labels: Optional[List[str]] = Field(
        default=None,
        description="Optional list of labels for each bar. If not provided, indices will be used.",
    )
    title: str = Field(default="Bar Chart", description="Title of the bar chart")


@tool("barchart-tool", args_schema=BarChartInput, return_direct=True)
def barchart_tool(
    data: List[float],
    labels: Optional[List[str]] = None,
    title: str = "Bar Chart",
) -> str:
    """Creates a bar chart from the input data and returns it as a base64 encoded image.

    Args:
        data (List[float]): List of numerical values for the bar chart
        labels (List[str], optional): Labels for each bar. Defaults to None.
        title (str, optional): Title of the chart. Defaults to "Bar Chart".

    Returns:
        str: Base64 encoded image of the bar chart
    """
    print("---BARCHART-TOOL---")
    # Create figure and axis
    plt.figure(figsize=(10, 6))

    # Create bars
    x = range(len(data))
    plt.bar(x, data)

    # Add labels if provided
    if labels:
        plt.xticks(x, labels, rotation=45)

    # Add title and labels
    plt.title("Bar Chart")
    plt.xlabel("Categories")
    plt.ylabel("Values")

    # Adjust layout to prevent label cutoff
    plt.tight_layout()

    # Save plot to bytes buffer
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png")
    plt.close()

    # Convert to base64
    image_base64 = base64.b64encode(buffer.getvalue()).decode()

    return image_base64
