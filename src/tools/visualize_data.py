from typing import Annotated
import os
import httpx
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import shape, mapping
from pystac_client import Client
from stackstac import stack
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from odc.stac import configure_rio, stac_load

import sys
import asyncio
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from src.tools.pick_aoi import pick_aoi


DATE_PROMPT = ChatPromptTemplate.from_messages([
    ("user", """Extract the start and end dates in format YYYY-MM-DD from the following query. Return both fields.

Query: {query}
""")
])
DATE_MODEL = ChatAnthropic(model="claude-3-5-sonnet-latest")


class DateRange(BaseModel):
    start_date: str = Field(default="2024-04-01")
    end_date: str = Field(default="2024-04-30")


def extract_dates_from_query(query: str) -> DateRange:
    chain = DATE_PROMPT | DATE_MODEL.with_structured_output(DateRange)
    return chain.invoke({"query": query})


async def run_visualization_from_query(query: str) -> Command:
    """
    Extract AOI + date range from query, pull Sentinel-2, save PNG.
    """
    print("query:", query)

    try:
        print("Reached start of process_aoi()")

        try:
            aoi_result = await pick_aoi.ainvoke({
                "type": "tool_call",
                "name": "pick-aoi",
                "args": {"question": query, "place": query},
                "id": "dev-run"
            })

            print("AOI result update:", aoi_result)
        except Exception as e:
            print("Error running pick_aoi:", e)
            raise

        aoi = aoi_result.update["aoi"]
        print("AOI keys:", aoi.keys())

        aoi_name = aoi.get("name")
        source = aoi.get("source")
        src_id = aoi.get("src_id")

        if not source or not src_id:
            raise ValueError("AOI did not return source/src_id")

        # Fetch geometry from API
        api_url = f"http://localhost:8000/api/geometry/{source}/{src_id}"
        headers = {"Authorization": f"Bearer {os.environ.get('API_TOKEN', '')}"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, headers=headers)
            resp.raise_for_status()
            geojson_resp = resp.json()

        if "geometry" not in geojson_resp:
            raise ValueError("No geometry returned from API")

        aoi_geojson = geojson_resp["geometry"]

        # Extract dates
        dates = extract_dates_from_query(query)
        start_date, end_date = dates.start_date, dates.end_date

        # Search Sentinel-2
        geometry = shape(aoi_geojson)
        catalog = Client.open("https://earth-search.aws.element84.com/v1")
        search = catalog.search( 
            collections=["sentinel-2-l2a"],
            datetime=f"{start_date}/{end_date}",
            bbox=geometry.bounds,
            #limit=100,
        )
        items = list(search.items())
        print("items ", len(items))

        if not items:
            raise ValueError("No Sentinel-2 items found.")

        stack_arr = stac_load(
            items,
            bands=("red", "green", "blue", "scl"),
            resolution=60,
            chunks={'x': 1024, 'y': 1024, 'bands': -1, 'time': -1},
            bounds=geometry.bounds,
        )
        print("stack_arr.dims ", stack_arr.dims)

        # Define invalid SCL classes
        invalid_scl = [0, 1, 3, 8, 9, 10, 11]
        # Mask using SCL band
        mask = ~stack_arr['scl'].isin(invalid_scl)
        # Apply mask only to RGB bands
        stack_arr_rgb = stack_arr[["red", "green", "blue"]].where(mask)
        # Temporal composite
        rgb = stack_arr_rgb.median(dim='time', skipna=True)
        # Convert to numpy
        rgb_np = np.stack([rgb[b].values for b in ["red", "green", "blue"]], axis=-1)
        # Normalize with contrast stretch
        rgb_min, rgb_max = np.nanpercentile(rgb_np, (2, 98))
        rgb_img = np.clip((rgb_np - rgb_min) / (rgb_max - rgb_min), 0, 1)

        # Save as PNG
        png_path = f"s2_{aoi_name.replace(' ', '_').replace(',', '')}_{start_date}_{end_date}.png"
        plt.imsave(png_path, rgb_img)
        print("Saved PNG to:", png_path)

        return Command(update={
            "s2_image_path": png_path,
            "aoi": aoi_name,
            "source": source,
            "src_id": src_id,
            "start_date": start_date,
            "end_date": end_date,
            "messages": [
                ToolMessage(
                    content=f"Saved Sentinel-2 visualization for **{aoi_name}** ({start_date} to {end_date}) from {source}:{src_id} → `{png_path}`."
                )
            ]
        })

    except Exception as e:
        return Command(update={
            "messages": [
                ToolMessage(
                    content=f"Failed to visualize Sentinel-2 data: {str(e)}",
                    tool_call_id="dev-run"
                )
            ]
        })

@tool("visualize-data")
async def visualize_sentinel2_from_query(query: str) -> Command:
    """Wrapper tool to run Sentinel-2 visualization from query."""
    return await run_visualization_from_query(query)


if __name__ == "__main__":
    result = asyncio.run(
        visualize_sentinel2_from_query.ainvoke({"query": "show me Lisbon Portugal in summer of 2025"})
    )
    print("Image saved to:", result.update.get("s2_image_path"))
    print("Full command result:", result.update)
