from typing import Annotated
import os
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
from shapely.geometry import shape
from pystac_client import Client
from stackstac import stack
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from src.tools.pick_aoi import pick_aoi


# Date extraction prompt + structured output model
DATE_PROMPT = ChatPromptTemplate.from_messages([
    ("user", """Extract the start and end dates in format YYYY-MM-DD from the following query. Return both fields.

Query: {query}
""")
])

DATE_MODEL = ChatAnthropic(model="claude-3-sonnet-20240229")

class DateRange(BaseModel):
    start_date: str = Field(default="2024-04-01")
    end_date: str = Field(default="2024-04-30")


def extract_dates_from_query(query: str) -> DateRange:
    chain = DATE_PROMPT | DATE_MODEL.with_structured_output(DateRange)
    return chain.invoke({"query": query})


def run_visualization_from_query(query: str) -> Command:
    """
    Extract AOI and date range from a query (e.g. "Osaka in April 2024"), pulls Sentinel-2 data, and saves a PNG.
    """
    try:
        aoi_result = pick_aoi.invoke({
            "type": "tool_call",
            "name": "pick-aoi",
            "args": {
                "question": query,
                "place": query,
            },
            "tool_call_id": "dev-run"
        })


        print("AOI result update:", aoi_result.update)

        aoi_geojson = aoi_result.update["aoi"]["geometry"]
        aoi_name = aoi_result.update["aoi"]["name"]

        dates = extract_dates_from_query(query)
        start_date = dates.start_date
        end_date = dates.end_date

        geometry = shape(aoi_geojson)
        catalog = Client.open("https://earth-search.aws.element84.com/v1/")
        search = catalog.search(
            collections=["sentinel-2-l2a"],
            datetime=f"{start_date}/{end_date}",
            bbox=geometry.bounds,
            limit=100,
        )
        items = list(search.items())
        if not items:
            raise ValueError("No Sentinel-2 items found.")

        stack_arr = stack(
            items,
            assets=["red", "green", "blue"],
            resolution=10,
            chunksize=1024,
            bounds=geometry.bounds,
            dtype="uint16"
        )

        rgb = stack_arr.sel(band=["red", "green", "blue"]).isel(time=-1)
        rgb_np = np.clip((rgb / 3000).transpose("band", "y", "x").data.compute(), 0, 1)
        rgb_img = np.moveaxis(rgb_np, 0, -1)

        os.makedirs("output", exist_ok=True)
        path = f"output/s2_{aoi_name.replace(' ', '_')}_{start_date}.png"

        plt.figure(figsize=(8, 8))
        plt.imshow(rgb_img)
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()

        print("AOI result:", aoi_result)
        print("Dates:", start_date, end_date)
        print("Found", len(items), "items")

        return Command(update={
            "s2_image_path": path,
            "aoi": aoi_name,
            "start_date": start_date,
            "end_date": end_date,
            "messages": [
                ToolMessage(
                    content=f"Saved Sentinel-2 visualization for **{aoi_name}** ({start_date} to {end_date}) to `{path}`."
                    # no tool_call_id here
                )
            ]
        })

    except Exception as e:
        return Command(update={
            "messages": [
                #ToolMessage(content=f"Failed to visualize Sentinel-2 data: {str(e)}")
                ToolMessage(content=f"Failed to visualize Sentinel-2 data: {str(e)}", tool_call_id="dev-run")
            ]
        })


@tool("visualize-data")
def visualize_sentinel2_from_query(query: str) -> Command:
    """
    Extract AOI and date range from a natural language query (e.g. 'Mogadishu in June 2024'),
    then download and visualize Sentinel-2 imagery as an RGB PNG image.
    """
    return run_visualization_from_query(query)


if __name__ == "__main__":
    result = visualize_sentinel2_from_query.invoke({"query": "Mogadishu in June 2024"})
    print("Image saved to:", result.update.get("s2_image_path"))
    print("Full command result:", result.update)

