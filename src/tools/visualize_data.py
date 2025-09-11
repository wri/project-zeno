from typing import Annotated
import os
import httpx
from shapely.geometry import shape
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
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
    Extract AOI + date range from query, return a Titiler-STACAPI URL for Sentinel-2 RGB imagery.
    """
    print("query:", query)

    try:
        aoi_result = await pick_aoi.ainvoke({
            "type": "tool_call",
            "name": "pick-aoi",
            "args": {"question": query, "place": query},
            "id": "dev-run"
        })
        aoi = aoi_result.update["aoi"]
        aoi_name = aoi.get("name")
        source = aoi.get("source")
        src_id = aoi.get("src_id")

        if not source or not src_id:
            raise ValueError("AOI did not return source/src_id")

        # Fetch geometry
        api_url = f"http://localhost:8000/api/geometry/{source}/{src_id}"
        headers = {"Authorization": f"Bearer {os.environ.get('API_TOKEN', '')}"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, headers=headers)
            resp.raise_for_status()
            geojson_resp = resp.json()

        if "geometry" not in geojson_resp:
            raise ValueError("No geometry returned from API")

        aoi_geojson = geojson_resp["geometry"]
        geometry = shape(aoi_geojson)
        bbox = geometry.bounds  # (minx, miny, maxx, maxy)

        # Date extraction
        dates = extract_dates_from_query(query)
        start_date, end_date = dates.start_date, dates.end_date

        # Build Titiler-STACAPI tile URL
        titiler_url = "http://127.0.0.1:8080"
        tile_url = (
            f"{titiler_url}/collections/sentinel-2-l2a/WebMercatorQuad/map"
            f"?assets=red&assets=green&assets=blue"
            f"&rescale=0,10000"
            f"&datetime={start_date}/{end_date}"
            f"&bbox={','.join(map(str, bbox))}"
            f"&minzoom=11"
        )

        print(f"{tile_url}")

        return Command(update={
            "titiler_url": tile_url,
            "aoi": aoi_name,
            "source": source,
            "src_id": src_id,
            "start_date": start_date,
            "end_date": end_date,
            "messages": [
                {
                    "content": f"Sentinel-2 RGB composite for **{aoi_name}** ({start_date} → {end_date}) → `{tile_url}`"
                }
            ]
        })

    except Exception as e:
        return Command(update={
            "messages": [
                ToolMessage(
                    content=f"Failed to generate Titiler URL: {str(e)}",
                    tool_call_id="dev-run"
                )
            ]
        })


@tool("visualize-data")
async def visualize_sentinel2_from_query(query: str) -> Command:
    """Wrapper tool to return a Titiler URL for Sentinel-2 visualization from query."""
    return await run_visualization_from_query(query)


if __name__ == "__main__":
    result = asyncio.run(
        visualize_sentinel2_from_query.ainvoke({"query": "show me Lisbon Portugal in summer of 2025"})
    )
    print("Titiler URL:", result.update.get("titiler_url"))
    print("Full command result:", result.update)
