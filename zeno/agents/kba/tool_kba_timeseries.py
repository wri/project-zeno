import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Dict, List, Optional

import geopandas as gpd
import pandas as pd
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field, constr, validator

from zeno.agents.kba.prompts import (
    KBA_TS_COLUMN_SELECTION_PROMPT,
    KBA_TS_INSIGHTS_PROMPT,
)

data_dir = Path("data/kba")
kba_ts_data = pd.read_parquet(data_dir / "kba_timeseries_data.parquet")

haiku = ChatAnthropic(model="claude-3-5-haiku-latest")
# sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest")


class InsightType(str, Enum):
    TIME_SERIES = "time_series"
    TREND = "trend"
    SEASONALITY = "seasonality"
    ANOMALY = "anomaly"


class TimeSeriesPoint(BaseModel):
    year: int = Field(
        ...,
        ge=1900,  # Reasonable lower bound
        le=datetime.now().year + 50,  # Allow some future projections
        description="Year of the observation",
    )
    value: float = Field(..., description="Numerical value for the time point")

    @validator("year")
    def validate_year(cls, v):
        current_year = datetime.now().year
        if v > current_year + 50:
            raise ValueError("Year cannot be more than 50 years in the future")
        return v


class TimeSeriesInsight(BaseModel):
    type: InsightType = Field(..., description="Type of time series insight")
    column: constr(min_length=1) = Field(
        ..., description="Name of the column/metric being analyzed"
    )
    title: constr(min_length=5) = Field(
        ..., description="Title describing the time series insight"
    )
    description: constr(min_length=20) = Field(
        ...,
        description="Detailed explanation of the time series pattern or finding",
    )
    data: List[TimeSeriesPoint] = Field(
        ...,
        min_items=2,  # Require at least 2 points for a time series
        description="Time series data points",
    )
    trend_direction: Optional[str] = Field(
        None,
        description="Overall trend direction (increasing, decreasing, stable)",
    )
    max_change: Optional[dict] = Field(
        None,
        description="Details about the maximum change between consecutive periods",
    )

    @validator("data")
    def validate_data_ordering(cls, v):
        # Ensure years are in chronological order
        years = [point.year for point in v]
        if years != sorted(years):
            raise ValueError(
                "Time series points must be in chronological order"
            )

        # Check for duplicate years
        if len(years) != len(set(years)):
            raise ValueError("Duplicate years found in time series")

        return v

    @validator("data")
    def calculate_trend(cls, v, values):
        # Calculate trend if not provided
        if len(v) >= 2:
            start_value = v[0].value
            end_value = v[-1].value
            if (
                "trend_direction" not in values
                or values["trend_direction"] is None
            ):
                if end_value > start_value * 1.05:  # 5% threshold
                    values["trend_direction"] = "increasing"
                elif end_value < start_value * 0.95:  # 5% threshold
                    values["trend_direction"] = "decreasing"
                else:
                    values["trend_direction"] = "stable"

            # Calculate max change if not provided
            if "max_change" not in values or values["max_change"] is None:
                max_change = 0
                max_change_years = (0, 0)
                for i in range(1, len(v)):
                    change = abs(v[i].value - v[i - 1].value)
                    if change > max_change:
                        max_change = change
                        max_change_years = (v[i - 1].year, v[i].year)

                values["max_change"] = {
                    "value": max_change,
                    "period": f"{max_change_years[0]}-{max_change_years[1]}",
                }

        return v


class TimeSeriesResponse(BaseModel):
    insights: List[TimeSeriesInsight] = Field(
        ...,
        min_items=1,
        description="List of time series insights from the analysis",
    )


class ColumnSelectionOutput(BaseModel):
    columns: List[str] = Field(
        ...,
        description="List of column names relevant to the user query based on knowledge base, user persona, and user query",
    )


column_selection_agent = haiku.with_structured_output(ColumnSelectionOutput)
time_series_agent = haiku.with_structured_output(TimeSeriesResponse)


@tool("kba-timeseries-tool")
def kba_timeseries_tool(question: str, state: Annotated[Dict, InjectedState]):
    """Find insights based on time series data for the Key Biodiversity Areas (KBAs).

    Args:
        question: The user's question or query
    """
    print("kba timeseries tool")
    user_persona = state["user_persona"]
    column_selection_prompt = KBA_TS_COLUMN_SELECTION_PROMPT.format(
        user_persona=user_persona,
    )
    columns = column_selection_agent.invoke(
        [
            SystemMessage(content=column_selection_prompt),
            HumanMessage(content=question),
        ]
    ).columns

    # add sitecode and year to the columns list if they are not already in the list
    if "sitecode" not in columns:
        columns.append("sitecode")
    if "year" not in columns:
        columns.append("year")

    # get selected kba within AOI
    kba_within_aoi = state["kba_within_aoi"]
    kba_within_aoi = gpd.GeoDataFrame.from_features(json.loads(kba_within_aoi))

    # get sitecodes within the AOI
    sitecodes = kba_within_aoi["sitecode"].unique()

    # filter the kba_ts_data for the sitecodes within the AOI
    kba_ts_data_filtered = kba_ts_data[kba_ts_data["sitecode"].isin(sitecodes)]

    # filter the kba_ts_data for the columns in the columns list
    kba_ts_data_filtered = kba_ts_data_filtered[columns]

    kba_ts_insights_prompt = KBA_TS_INSIGHTS_PROMPT.format(
        user_persona=user_persona,
        question=question,
        data=kba_ts_data_filtered.to_csv(index=False),
    )

    response = time_series_agent.invoke(kba_ts_insights_prompt)

    return json.loads(response.json())
