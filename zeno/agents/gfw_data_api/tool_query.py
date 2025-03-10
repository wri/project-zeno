import os

from typing import Any, Dict, List, Optional, Tuple, Any

import requests
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from zeno.agents.gfw_data_api.prompts import (
    prep_datatables_selection_prompt,
    prep_field_selection_prompt,
)
import csv
import io

GFW_DATA_API_BASE_URL = os.getenv(
    "GFW_DATA_API_BASE_URL", "https://data-api.globalforestwatch.org/"
)


def build_table_slug(gadm_level: int, table: str) -> str:
    table_gadm_level = "iso" if gadm_level == 0 else f"adm{gadm_level}"
    category_name = "integrated_alerts" if table == "daily_alerts" else "tcl"
    table_slug = f"gadm__{category_name}__{table_gadm_level}_{table}"
    return table_slug


def fetch_table_fields(table_slug: str) -> str:
    dataset = requests.get(
        f"{GFW_DATA_API_BASE_URL}/dataset/{table_slug}",
        headers={"Authorization": f"Bearer: {os.environ['GFW_DATA_API_KEY']}"},
    ).json()
    # TODO: assert the query succeeded
    latest_version = sorted(dataset["data"]["versions"])[-1]

    # This contains an asset URI with tiling endpoint for the precomputed raster (.pbf)!
    table_metadata = requests.get(
        f"{GFW_DATA_API_BASE_URL}/assets?dataset={table_slug}&version={latest_version}",
        headers={"Authorization": f"Bearer: {os.environ['GFW_DATA_API_KEY']}"},
    ).json()
    # TODO: assert the query succeeded

    table_metadata = table_metadata["data"][0]["metadata"]
    fields = [
        {
            "name": f["name"],
            "description": (
                f["description"] if f["description"] else " ".join(f["name"].split("_"))
            ),
            "data_type": f["data_type"],
        }
        for f in table_metadata["fields"]
    ]
    # Create a string buffer to hold CSV data
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=["name", "description", "data_type"])
    writer.writeheader()
    writer.writerows(fields)

    # Get the CSV string
    csv_output = csv_buffer.getvalue()
    csv_buffer.close()
    return csv_output


class QueryInput(BaseModel):
    """Input schema for location finder tool"""

    gadm_level: int = Field(description="GADM level of place or places to be queried")
    gadm_ids: List[str] = Field(description="A list of one or more GADM IDs to query")
    query: str = Field(description="The user's query")


@tool(
    "query-tool",
    args_schema=QueryInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def query_tool(
    gadm_level: int,
    gadm_ids: Optional[str],
    query: str,
) -> Tuple[List[Tuple[Any]], List[Dict[str, Any]]]:
    """ """
    # TODO: as we add more tables, this should become a HIL
    # tool that prompts the user to select within a preselection of
    # 3-5 tables
    from zeno.agents.gfw_data_api.models import haiku

    model_resp = haiku.invoke(
        [HumanMessage(prep_datatables_selection_prompt(query))]
    ).content

    table, description = model_resp.split(",")

    table_slug = build_table_slug(gadm_level, table)
    table_gadm_level = "iso" if gadm_level == 0 else f"adm{gadm_level}"

    fields = fetch_table_fields(table_slug)

    from zeno.agents.gfw_data_api.models import haiku

    sql_query = haiku.invoke(
        [
            HumanMessage(
                prep_field_selection_prompt(
                    query=query,
                    table_slug=table_slug,
                    fields=fields,
                    gadm_level=table_gadm_level,
                    gadm_ids=gadm_ids,
                )
            )
        ]
    ).content

    return (
        sql_query,
        {
            "table_slug": table_slug,
            "fields": fields,
            "gadm_ids": gadm_ids,
            "gadm_level": table_gadm_level,
            "query": query,
            "sql_query": sql_query,
        },
    )
