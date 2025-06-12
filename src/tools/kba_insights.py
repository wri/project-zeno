import json
from functools import lru_cache
from enum import Enum
from typing import Annotated, Any, Dict, List, Union

import geopandas as gpd
import pandas as pd
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field

from src.tools.utils.prompts import (
    KBA_COLUMN_SELECTION_PROMPT,
    KBA_INSIGHTS_PROMPT,
)

haiku = ChatAnthropic(model="claude-3-5-haiku-latest")
sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest")


class InsightType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    CHART = "chart"


class ChartData(BaseModel):
    categories: List[Union[str, int, float]] = Field(
        ..., description="Categories for the chart axis"
    )
    values: List[Union[int, float]] = Field(
        ..., description="Numerical values corresponding to categories"
    )
    unit: str = Field(..., description="Unit of the data")


class Insight(BaseModel):
    type: InsightType = Field(..., description="Type of insight visualization")
    title: str = Field(..., description="Title for the insight")
    description: str = Field(..., description="Explanation of what the insight shows")
    data: Union[str, List[Dict[str, Any]], ChartData] = Field(
        ..., description="Content of the insight, structure depends on type"
    )


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
insights_agent = sonnet.with_structured_output(InsightsResponse)

column_description = pd.read_csv("data/kba/kba_column_descriptions.csv")


@tool("kba-insights-tool")
def kba_insights_tool(question: str, state: Annotated[Dict, InjectedState]):
    """Find insights relevant to the user query for the Key Biodiversity Areas (KBAs).

    Args:
        question: The user's question
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

    return response.dict()
