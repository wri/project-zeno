from typing import Annotated, Dict, List
from pathlib import Path
import json
import pandas as pd
import geopandas as gpd
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import InjectedState

from zeno.agents.kba.prompts import KBA_TS_COLUMN_SELECTION_PROMPT, KBA_TS_INSIGHTS_PROMPT

data_dir = Path("data/kba")
kba_ts_data = pd.read_parquet(data_dir / "kba_timeseries_data.parquet")

sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest")

class ColumnSelectionOutput(BaseModel):
    columns: List[str] = Field(
        ...,
        description="List of column names relevant to the user query based on knowledge base, user persona, and user query",
    )

column_selection_agent = sonnet.with_structured_output(ColumnSelectionOutput)

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
    columns = column_selection_agent.invoke([SystemMessage(content=column_selection_prompt), HumanMessage(content=question)]).columns

    # add sitecode and year to the columns list if they are not already in the list
    if "sitecode" not in columns:
        columns.append("sitecode")
    if "year" not in columns:
        columns.append("year")

    print(columns)

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

    response = sonnet.invoke(kba_ts_insights_prompt)

    return response.content
