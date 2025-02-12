import json
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional, Union

import geopandas as gpd
import pandas as pd
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field, constr, validator

from zeno.agents.kba.prompts import (
    KBA_COLUMN_SELECTION_PROMPT,
    KBA_INSIGHTS_PROMPT,
)

haiku = ChatAnthropic(model="claude-3-5-haiku-latest")
# sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest")


class InsightType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    CHART = "chart"


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"


class ChartData(BaseModel):
    categories: List[Union[str, int, float]] = Field(
        ..., description="Categories for the chart axis"
    )
    values: List[Union[int, float]] = Field(
        ..., description="Numerical values corresponding to categories"
    )

    @validator("categories")
    def validate_categories_length(cls, v, values):
        if "values" in values and len(v) != len(values["values"]):
            raise ValueError("Categories and values must have the same length")
        return v


class Insight(BaseModel):
    type: InsightType = Field(..., description="Type of insight visualization")
    title: constr(min_length=5) = Field(
        ..., description="Title for the insight"
    )
    data: Union[str, List[Dict[str, Any]], ChartData] = Field(
        ..., description="Content of the insight, structure depends on type"
    )
    chart_type: Optional[ChartType] = Field(
        None, description="Type of chart when insight type is 'chart'"
    )
    description: constr(min_length=10) = Field(
        ..., description="Explanation of what the insight shows"
    )

    @validator("chart_type")
    def validate_chart_type(cls, v, values):
        if values.get("type") == InsightType.CHART and v is None:
            raise ValueError("chart_type is required when type is 'chart'")
        if values.get("type") != InsightType.CHART and v is not None:
            raise ValueError(
                "chart_type should only be present when type is 'chart'"
            )
        return v

    @validator("data")
    def validate_data_type(cls, v, values):
        insight_type = values.get("type")
        if insight_type == InsightType.TEXT and not isinstance(v, str):
            raise ValueError("Data must be a string for text insights")
        elif insight_type == InsightType.TABLE and not isinstance(v, list):
            raise ValueError(
                "Data must be a list of dictionaries for table insights"
            )
        elif insight_type == InsightType.CHART and not isinstance(
            v, (dict, ChartData)
        ):
            raise ValueError("Data must be ChartData for chart insights")
        return v


class InsightsResponse(BaseModel):
    insights: List[Insight] = Field(
        ...,
        min_items=1,
        description="List of insights generated from the analysis",
    )


class ColumnSelectionOutput(BaseModel):
    columns: List[str] = Field(
        ...,
        description="List of column names relevant to the user query based on knowledge base, user persona, and user query",
    )


column_selection_agent = haiku.with_structured_output(ColumnSelectionOutput)
insights_agent = haiku.with_structured_output(InsightsResponse)

column_description = pd.read_csv("data/kba/kba_column_descriptions.csv")


@tool("kba-insights-tool")
def kba_insights_tool(question: str, state: Annotated[Dict, InjectedState]):
    """Find insights relevant to the user query for the Key Biodiversity Areas (KBAs).

    Args:
        question: The user's question or query
    """
    print("kba insights tool")
    kba_within_aoi = state["kba_within_aoi"]
    kba_within_aoi = gpd.GeoDataFrame.from_features(json.loads(kba_within_aoi))
    user_persona = state["user_persona"]

    column_selection_prompt = KBA_COLUMN_SELECTION_PROMPT.format(
        user_persona=user_persona,
        question=question,
        dataset_description=column_description.to_csv(index=False),
    )
    columns = column_selection_agent.invoke(
        [
            AIMessage(content=column_selection_prompt),
            HumanMessage(content=question),
        ]
    ).columns
    # add siteName and sitecode to the columns list if they are not already in the list
    if "siteName" not in columns:
        columns.append("siteName")
    if "sitecode" not in columns:
        columns.append("sitecode")
    # remove geometry column if it is in the columns list
    if "geometry" in columns:
        columns.remove("geometry")

    kba_within_aoi_filtered = kba_within_aoi[columns]

    kba_insights_prompt = KBA_INSIGHTS_PROMPT.format(
        user_persona=user_persona,
        question=question,
        column_description=column_description[
            column_description["column"].isin(columns)
        ].to_csv(index=False),
        data=kba_within_aoi_filtered.to_csv(index=False),
    )

    response = insights_agent.invoke(kba_insights_prompt)

    return json.loads(response.json())
