import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Dict

import geopandas as gpd
import pandas as pd
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field

from src.tools.utils.prompts import KBA_TIMESERIES_INSIGHTS_PROMPT

data_dir = Path("data/kba")
kba_ts_data = pd.read_parquet(data_dir / "kba_timeseries_data.parquet")

sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0)


class Insight(BaseModel):
    type: str = Field(..., description="Type of insight")
    title: str = Field(..., description="Title for the insight")
    description: str = Field(..., description="Brief explanation of what this shows")
    analysis: str = Field(..., description="Provide data driven insights")


insights_agent = sonnet.with_structured_output(Insight)
column_mapper = {
    "gpp": "Annual gross primary productivity in gC/m2",
    "cultivated": "Annual managed grassland area in hectares",
    "nsn": "Annual native/unmanaged grassland area in hectares",
    "gfw_forest_carbon_gross_emissions_all_gases": "Annual forest GHG emissions in tonnes CO2e",
    "umd_tree_cover_loss": "Annual tree cover loss in hectares",
}


@tool("kba-timeseries-tool")
def kba_timeseries_tool(column: str, state: Annotated[Dict, InjectedState]):
    """Find insights based on time series data for the Key Biodiversity Areas (KBAs).

    Args:
        column: The column name to get time series data for each KBA.
        Pick one of the following:
            - gpp: Annual gross primary productivity in gC/m2
            - cultivated: Annual managed grassland area in hectares
            - nsn: Annual native/unmanaged grassland area in hectares
            - gfw_forest_carbon_gross_emissions_all_gases: Annual forest GHG emissions in tonnes CO2e
            - umd_tree_cover_loss: Annual tree cover loss in hectares
    """
    print("kba timeseries tool")

    # get selected kba within AOI
    kba_within_aoi = state["kba_within_aoi"]
    kba_within_aoi = gpd.GeoDataFrame.from_features(json.loads(kba_within_aoi))

    # get sitecodes within the AOI
    sitecodes = kba_within_aoi["sitecode"].unique()

    # filter the kba_ts_data for the sitecodes within the AOI
    kba_ts_data_filtered = kba_ts_data[kba_ts_data["sitecode"].isin(sitecodes)]

    # filter the kba_ts_data for the column
    kba_ts_data_filtered = kba_ts_data_filtered[["sitename", "year", column]]

    # pivot the data to get the year as index and sitename as columns
    kba_ts_data_pivoted = kba_ts_data_filtered.pivot(
        index="year", columns="sitename", values=column
    )

    # get insights
    response = insights_agent.invoke(
        KBA_TIMESERIES_INSIGHTS_PROMPT.format(
            user_persona=state["user_persona"],
            column=column,
            data=kba_ts_data_pivoted.to_csv(),
        )
    )

    return {
        "data": kba_ts_data_pivoted.reset_index().to_dict(orient="records"),
        "ylabel": column_mapper[column],
        "xlabel": "Year",
        "type": "timeseries",
        "title": response.title,
        "description": response.description,
        "analysis": response.analysis,
    }
