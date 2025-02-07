import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Annotated
from uuid import uuid4

import geopandas as gpd
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import InjectedState

from pydantic import BaseModel, Field

from zeno.agents.kba.prompts import KBA_INSIGHTS_PROMPT, KBA_COLUMN_SELECTION_PROMPT

sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest")

class ColumnSelectionOutput(BaseModel):
    columns: List[str] = Field(
        ...,
        description="List of column names relevant to the user query based on knowledge base, user persona, and user query",
    )

column_selection_agent = sonnet.with_structured_output(ColumnSelectionOutput)

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
        [AIMessage(content=column_selection_prompt),
        HumanMessage(content=question)]
    ).columns
    print(columns)
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
        column_description=column_description[column_description['column'].isin(columns)].to_csv(index=False),
        data=kba_within_aoi_filtered.to_csv(index=False),
    )

    response = sonnet.invoke(kba_insights_prompt)

    return response.content
