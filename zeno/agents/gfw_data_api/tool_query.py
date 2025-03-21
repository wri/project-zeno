import os

from typing import Any, Dict, List, Optional, Annotated
import requests
from langgraph.types import Command
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field, model_validator
from zeno.agents.gfw_data_api.prompts import (
    prep_datatables_selection_prompt,
    prep_field_selection_prompt,
    prep_api_sql_query_prompt,
    prep_sql_query_explanation_prompt,
    prep_query_results_explanation_prompt,
    prep_modify_sql_query_prompt,
    prep_sql_query_modified_explanation_prompt,
)
import csv
import io
import json

GFW_DATA_API_BASE_URL = os.getenv(
    "GFW_DATA_API_BASE_URL", "https://www.globalforestwatch.org/api/data"
)


class GenerateQueryInput(BaseModel):
    """Input schema for query generation tool."""

    gadm_level: int = Field(description="GADM level of place or places to be queried")
    gadm_ids: Optional[List[str]] = Field(
        description="A list of one or more GADM IDs to query", default=[]
    )
    user_query: str = Field(description="The user's query")
    tool_call_id: str = Field(description="The ID of the tool call")


class ExecuteQueryInput(BaseModel):
    """Input schema for query execution tool."""

    sql_query: str = Field(description="The SQL query to be executed")
    table_slug: str = Field(
        description="The identifier (slug) of the table to be queried"
    )


class ModifyQueryInput(BaseModel):
    modification: Optional[str] = Field(
        description="User requested modification to the query", default=""
    )
    user_query: str = Field(description="The user's query")
    sql_query: str = Field(description="The SQL query to be modified")
    error: Optional[str] = Field(
        description="Error message returned by the GFW Data API", default=""
    )
    modification: Optional[str] = Field(
        description="User requested modification to the query", default=""
    )


class ExplainQueryResultsInput(BaseModel):
    """Input schema for query results explanation tool."""

    user_query: str = Field(description="The user's query")
    data: Dict[str, Any] = Field(description="The data returned by the query")


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
    gadm_id: Optional[str] = ""
    gadm_level: Optional[int] = -1
    iso: Optional[str] = ""
    adm1: Optional[int] = 0
    adm2: Optional[int] = 0

    # TODO: add a validator to ensure that the GADM ID is well-formed
    # and that the iso/adm1/adm2 levels correspond to the GADM ID
    # (if supplied)

    @model_validator(mode="after")
    def parse_id(self):

        if not self.gadm_id and not self.iso:
            raise ValueError(
                "Either a GADM ID or ISO, ADM1, and ADM2 must be provided."
            )

        if self.iso:
            self.gadm_id = self.iso
            self.gadm_level = 0
        if self.adm1:
            if not self.iso:
                raise ValueError("ISO must be provided if ADM1 is provided.")
            self.gadm_id = f"{self.iso}.{self.adm1}"
            self.gadm_level = 1
        if self.adm2:
            if not self.iso or not self.adm1:
                raise ValueError("ISO and ADM1 must be provided if ADM2 is provided.")
            self.gadm_id = f"{self.iso}.{self.adm1}.{self.adm2}"
            self.gadm_level = 2

        if self.gadm_id:
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

    def lookup(self):
        gids = []
        if self.gadm_level == 0:
            from zeno.agents.gfw_data_api.tool_location import gadm_0

            gids = [g for g in gadm_0 if g["GID_0"].startswith(self.gadm_id)]
        if self.gadm_level == 1:
            from zeno.agents.gfw_data_api.tool_location import gadm_1

            gids = [g for g in gadm_1 if g["GID_1"].startswith(self.gadm_id)]
        if self.gadm_level == 2:
            from zeno.agents.gfw_data_api.tool_location import gadm_2

            gids = [g for g in gadm_2 if g["GID_2"].startswith(self.gadm_id)]
        if not gids:
            raise ValueError(f"No GADM object for ID: {self.gadm_id} found")
        return dict(gids[0].properties)

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
    "generate-query-tool",
    args_schema=GenerateQueryInput,
    return_direct=False,
    # response_format="content_and_artifact",
)
def generate_query_tool(
    user_query: str,
    gadm_level: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
    gadm_ids: Optional[List[str]] = [],
) -> Command:
    """
    Returns a SQL query that can be run against the GFW Data API to answer
    the user's question, along with an explanation of each part of the SQL
    query, and how it relates to the user's question. Ends with asking the user
    if they would like to make any changes to the query before it is executed.
    """

    # TODO: as we add more tables, this should become a HIL
    # tool that prompts the user to select within a preselection of
    # 3-5 tables

    from zeno.agents.gfw_data_api.models import haiku

    model_resp = haiku.with_structured_output(DatatableSelection).invoke(
        [HumanMessage(prep_datatables_selection_prompt(user_query=user_query))]
    )

    table_slug = build_table_slug(gadm_level, model_resp.table)
    table_gadm_level = (
        "iso"
        if gadm_level == 0
        else ("iso,adm1" if gadm_level == 1 else "iso,adm1,adm2")
    )

    # Fetch feilds in table to allow LLM to craft an appropriate
    # query
    fields = fetch_table_fields(table_slug)

    fields_to_query = haiku.with_structured_output(FieldSelection).invoke(
        [
            HumanMessage(
                content=prep_field_selection_prompt(
                    user_query=user_query, fields=fields.as_csv()
                )
            )
        ]
    )

    location_filter = " OR ".join(
        [GadmId(gadm_id=gadm_id).as_sql_filter() for gadm_id in gadm_ids]
    )

    sql_query = haiku.invoke(
        [
            HumanMessage(
                content=prep_api_sql_query_prompt(
                    user_query=user_query,
                    fields_to_query=fields_to_query.as_csv(),
                    gadm_level=table_gadm_level,
                    location_filter=location_filter,
                )
            )
        ]
    ).content

    explanation = haiku.invoke(
        [
            HumanMessage(
                content=prep_sql_query_explanation_prompt(
                    user_query=user_query, sql_query=sql_query
                )
            )
        ]
    ).content

    # TODO: add automated handling for failed query, with reformulating and retrying it
    # TODO: add HIL to confirm generated SQL before executing
    # TODO: add interpretation/reporting for query

    return Command(
        update={
            "table_slug": table_slug,
            "fields_available": fields.as_csv(),
            "fields_to_query": fields_to_query.as_csv(),
            "gadm_ids": gadm_ids,
            "gadm_level": table_gadm_level,
            "user_query": user_query,
            "sql_query": sql_query,
            "explanation": explanation,
            "messages": ToolMessage(
                content=f"In response to your question: {user_query}, I have generated the following SQL query: \n {sql_query} \n Here's an explanation of the query was constructed: \n {explanation}. Please describe any modifications you would like to make to the query, or confirm that I can execute it!",
                artifact={
                    "table_slug": table_slug,
                    "fields_available": fields.as_csv(),
                    "fields_to_query": fields_to_query.as_csv(),
                    "gadm_ids": gadm_ids,
                    "gadm_level": table_gadm_level,
                    "user_query": user_query,
                    "sql_query": sql_query,
                    "explanation": explanation,
                },
                tool_call_id=tool_call_id,
            ),
        },
        goto="gfw_data_api",
    )


@tool(
    "modify-query-tool",
    args_schema=ModifyQueryInput,
    return_direct=False,
    # response_format="content_and_artifact",
)
def modify_query_tool(
    user_query: Annotated[str, InjectedState("user_query")],
    sql_query: Annotated[str, InjectedState("sql_query")],
    tool_call_id: Annotated[str, InjectedToolCallId],
    error: Optional[Annotated[str, InjectedState("user_query")]] = "",
    modification: Optional[str] = "",
) -> Command:
    """
    Modifies the query based on user input, and returns the modified query.
    """

    if not error and not modification:
        raise ValueError(
            "At least one of 'error' (GFW Data API error) or 'modification' (User requested modification) must be provided."
        )

    from zeno.agents.gfw_data_api.models import haiku

    modified_query = haiku.invoke(
        [
            HumanMessage(
                content=prep_modify_sql_query_prompt(
                    user_query=user_query,
                    sql_query=sql_query,
                    modification=modification,
                    error=error,
                )
            )
        ]
    ).content

    modified_explanation = haiku.invoke(
        [
            HumanMessage(
                content=prep_sql_query_modified_explanation_prompt(
                    user_query=user_query,
                    sql_query=sql_query,
                    modification=modification,
                    error=error,
                )
            )
        ]
    ).content

    return Command(
        update={
            "sql_query": modified_query,
            "error": "",
            "messages": ToolMessage(
                content=f"I've generated the following query: {modified_query}. Here is an explanation of the modifications I made to the query: {modified_explanation}. Do you want to make any changes before I execute it? (yes/no)",
                artifact={
                    "sql_query": modified_query,
                    "explanation": modified_explanation,
                },
                tool_call_id=tool_call_id,
            ),
        },
        goto="gfw_data_api",
    )


@tool(
    "execute-query-tool",
    args_schema=ExecuteQueryInput,
    return_direct=False,
    # response_format="content_and_artifact",
)
def execute_query_tool(
    sql_query: Annotated[str, InjectedState("sql_query")],
    table_slug: Annotated[str, InjectedState("table_slug")],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Executes a SQL query against the GFW Data API and returns the result."""

    print(f"Executing query: {sql_query}")
    print(f"Against table: {table_slug}")
    result = requests.post(
        f"{GFW_DATA_API_BASE_URL}/dataset/{table_slug}/latest/query/json",
        headers={"x-api-key": os.environ["GFW_DATA_API_KEY"]},
        json={"sql": sql_query},
    )
    print(f"Result: {result}")

    error = ""
    if result.status != 200:
        try:
            error = result.json()["message"]
        except json.JsonDecodeError:
            error = result.content

    result = result.json()
    if result["status"] != "success":
        error = result["message"]

    if error:
        return Command(
            update={
                "error": error,
                "messages": ToolMessage(
                    content=f"The query has returned the following error: {error}. I will try again with a modified query.",
                    tool_call_id=tool_call_id,
                ),
            },
            goto="gfw_data_api",
        )

    data = result["data"]

    return Command(
        update={
            "data": data,
            "messages": ToolMessage(
                content=f"Executed the following query: \n {sql_query} \n against table: {table_slug} with success, I will now explain the results.",
                artifact={"data": data},
                tool_call_id=tool_call_id,
            ),
        },
        goto="gfw_data_api",
    )


@tool(
    "explain-results-tool",
    args_schema=ExplainQueryResultsInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def explain_query_results_tool(
    user_query: Annotated[str, InjectedState("sql_query")],
    data: Annotated[str, InjectedState("data")],
):

    print(f"Expalaining query results: {data}")
    print(f"For query: {user_query}")

    gadm = None
    if "iso" in data.keys():
        gadm = GadmId(iso=data["iso"])

    elif "adm1" in data.keys():
        if "iso" not in data.keys():
            raise ValueError("ISO must be provided if ADM1 is provided.")
        gadm = GadmId(iso=data["iso"], adm1=data["adm1"])

    elif "adm2" in data.keys():
        if "iso" not in data.key() or "adm1" not in data.keys():
            raise ValueError("ISO and ADM1 must be provided if ADM2 is provided.")
        gadm = GadmId(iso=data["iso"], adm1=data["adm1"], adm2=data["adm2"])
    if not gadm:
        raise ValueError("No GADM ID found in query results")
    info = gadm.lookup()

    from zeno.agents.gfw_data_api.models import haiku

    explanation = haiku.invoke(
        [
            HumanMessage(
                content=prep_query_results_explanation_prompt(
                    user_query=user_query, query_results=data, location_info=info
                )
            )
        ]
    ).content
    return (
        explanation,
        {"user_query": user_query, "data": data, "location_info": info},
    )
