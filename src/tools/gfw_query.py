import os

from typing import Any, Dict, List, Optional, Tuple
import requests
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, model_validator
from src.tools.utils.prompts import (
    prep_datatables_selection_prompt,
    prep_field_selection_prompt,
    prep_api_sql_query_prompt,
    prep_sql_query_explanation_prompt,
)

import csv
import io

GFW_DATA_API_BASE_URL = os.getenv(
    "GFW_DATA_API_BASE_URL", "https://www.globalforestwatch.org/api/data"
)


class DatatableSelection(BaseModel):
    table: str
    description: str

    def __repr__(self):
        return f"Selected table: {self.table} (description: {self.description})"


class _FieldSelection(BaseModel):
    name: str
    description: str
    data_type: str

    def __repr__(self):
        return f"Field: {self.name} (description: {self.description}, type: {self.data_type})"


class FieldSelection(BaseModel):
    fields: List[_FieldSelection]

    def as_csv(self):

        # Create a string buffer to hold CSV data
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(
            csv_buffer, fieldnames=["name", "description", "data_type"]
        )
        writer.writeheader()
        writer.writerows([f.model_dump() for f in self.fields])

        # Get the CSV string
        csv_output = csv_buffer.getvalue()
        csv_buffer.close()

        return csv_output


def build_table_slug(gadm_level: int, table: str) -> str:
    table_gadm_level = "iso" if gadm_level == 0 else f"adm{gadm_level}"
    category_name = "integrated_alerts" if table == "daily_alerts" else "tcl"
    table_slug = f"gadm__{category_name}__{table_gadm_level}_{table}"
    return table_slug


def fetch_table_fields(table_slug: str) -> FieldSelection:
    dataset = requests.get(
        f"{GFW_DATA_API_BASE_URL}/dataset/{table_slug}",
        headers={"x-api-key": os.environ["GFW_DATA_API_KEY"]},
    ).json()
    # TODO: assert the query succeeded
    latest_version = sorted(dataset["data"]["versions"])[-1]

    # This contains an asset URI with tiling endpoint for the precomputed raster (.pbf)!
    table_metadata = requests.get(
        f"{GFW_DATA_API_BASE_URL}/assets?dataset={table_slug}&version={latest_version}",
        headers={"x-api-key": os.environ["GFW_DATA_API_KEY"]},
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

    return FieldSelection(fields=fields)


class GadmId(BaseModel):
    gadm_id: str
    gadm_level: Optional[int] = -1
    iso: Optional[str] = ""
    adm1: Optional[int] = -1
    adm2: Optional[int] = -1

    # TODO: add a validator to ensure that the GADM ID is well-formed
    # and that the iso/adm1/adm2 levels correspond to the GADM ID
    # (if supplied)

    @model_validator(mode="after")
    def parse_id(self):

        gadm_id = self.gadm_id

        if "_" in gadm_id:
            [gadm_id, _] = gadm_id.split("_")

        gadm_id = gadm_id.split(".")
        if len(gadm_id) == 1:
            [self.iso] = gadm_id
            self.gadm_level = 0

        if len(gadm_id) == 2:
            self.iso, self.adm1 = gadm_id[0], int(gadm_id[1])
            self.gadm_level = 1

        if len(gadm_id) > 2:
            self.iso, self.adm1, self.adm2 = (
                gadm_id[0],
                int(gadm_id[1]),
                int(gadm_id[2]),
            )
            self.gadm_level = 2
        return self

    def __repr__(self):
        return f"GADM ID: {self.gadm_id} (level: {self.gadm_level}). ISO: {self.iso}, ADM1: {self.adm1}, ADM2: {self.adm2}"

    def as_sql_filter(self):
        if self.gadm_level == 0:
            return f"(iso = '{self.iso}')"
        if self.gadm_level == 1:
            return f"(iso = '{self.iso}' AND adm1 = {self.adm1})"
        if self.gadm_level == 2:
            return f"(iso = '{self.iso}' AND adm1 = {self.adm1} AND adm2 = {self.adm2})"
        return ""


@tool(
    "gfw-query-tool",
    return_direct=False,
    response_format="content",
)
def gfw_query_tool(
    gadm_level: int,
    gadm_id: Optional[str],
    user_query: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Query the GFW data API. Use this tool ONLY to answer questions on a global scale like deforestation,
    biodiversity loss, etc. at country or subnational administrative divisions.

    Args:
        gadm_level: GADM level of place or places to be queried
        gadm_id: GADM id to search for. This can either be a GADM ID for a location to search directly (eg: Brazil) or it can be the ID of a relative location to search for (eg: states in Brazil)
        user_query: the user's query
    """
    # TODO: as we add more tables, this should become a HIL
    # tool that prompts the user to select within a preselection of
    # 3-5 tables
    from src.tools.utils.models import haiku

    model_resp = haiku.with_structured_output(DatatableSelection).invoke(
        [HumanMessage(prep_datatables_selection_prompt(user_query=user_query))]
    )

    table_slug = build_table_slug(gadm_level, model_resp.table)
    table_gadm_level = "iso" if gadm_level == 0 else f"adm{gadm_level}"

    # Fetch feilds in table to allow LLM to craft an appropriate
    # query
    fields = fetch_table_fields(table_slug)

    fields_to_query = haiku.with_structured_output(FieldSelection).invoke(
        [
            HumanMessage(
                prep_field_selection_prompt(
                    user_query=user_query, fields=fields.as_csv()
                )
            )
        ]
    )

    print(f"Fields to query: {fields_to_query.as_csv()}")

    sql_query = haiku.invoke(
        [
            HumanMessage(
                prep_api_sql_query_prompt(
                    user_query=user_query,
                    fields_to_query=fields_to_query.as_csv(),
                    gadm_level=table_gadm_level,
                    location_filter=GadmId(gadm_id=gadm_id).as_sql_filter(),
                )
            )
        ]
    ).content

    # explanation = haiku.invoke(
    #     [
    #         HumanMessage(
    #             prep_sql_query_explanation_prompt(
    #                 user_query=user_query, sql_query=sql_query
    #             )
    #         )
    #     ]
    # ).content

    result = requests.post(
        f"{GFW_DATA_API_BASE_URL}/dataset/{table_slug}/latest/query/json",
        headers={"x-api-key": os.environ["GFW_DATA_API_KEY"]},
        json={"sql": sql_query},
    ).json()

    # TODO: add automated handling for failed query, with reformulating and retrying it
    # TODO: add HIL to confirm generated SQL before executing
    # TODO: add interpretation/reporting for query

    # return (
    #     f"QUERY: {sql_query} \n EXPLANATION: {explanation}",
    #     {
    #         "table_slug": table_slug,
    #         "fields_available": fields.as_csv(),
    #         "fields_to_query": fields_to_query.as_csv(),
    #         "gadm_id": gadm_id,
    #         "gadm_level": table_gadm_level,
    #         "user_query": user_query,
    #         "sql_query": sql_query,
    #         "explanation": explanation,
    #         "result": result["data"],
    #     },
    # )

    return result["data"]
