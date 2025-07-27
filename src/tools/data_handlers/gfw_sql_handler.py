import csv
import io
import os
from typing import Any, Dict, List, Optional

import requests
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, model_validator

from src.tools.data_handlers.base import (
    DataPullResult,
    DataSourceHandler,
    dataset_names,
    gadm_levels,
)
from src.utils.llms import SONNET
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

GFW_DATA_API_BASE_URL = os.getenv(
    "GFW_DATA_API_BASE_URL", "https://www.globalforestwatch.org/api/data"
)


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


def fetch_table_fields(table_slug: str) -> FieldSelection:
    logger.debug(f"Fetching dataset info for table: {table_slug}")
    dataset_url = f"{GFW_DATA_API_BASE_URL}/dataset/{table_slug}"
    dataset = requests.get(
        dataset_url,
        headers={"x-api-key": os.environ["GFW_DATA_API_KEY"]},
    ).json()
    # TODO: assert the query succeeded
    latest_version = sorted(dataset["data"]["versions"])[-1]
    logger.debug(f"Using latest dataset version: {latest_version}")

    # This contains an asset URI with tiling endpoint for the precomputed raster (.pbf)!
    assets_url = (
        f"{GFW_DATA_API_BASE_URL}/assets?dataset={table_slug}&version={latest_version}"
    )
    table_metadata = requests.get(
        assets_url,
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
    logger.debug(f"Found {len(fields)} fields for table '{table_slug}'")
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


class GFWSQLHandler(DataSourceHandler):
    """Handler for standard GFW data sources (non-DIST-ALERT)"""

    def can_handle(self, dataset: Any, table_name: str) -> bool:
        return table_name != "DIST-ALERT"

    def pull_data(
        self,
        query: str,
        aoi: Dict,
        subregion_aois: List[Dict],
        subregion: str,
        subtype: str,
        dataset: Dict,
        start_date: str,
        end_date: str,
    ) -> DataPullResult:
        try:
            aoi_name = aoi["name"]
            table_name = dataset_names[dataset["data_layer"]]
            table_slug = self._determine_table_slug(table_name, subtype)

            logger.debug(f"Determined table slug: {table_slug}")
            table_fields = fetch_table_fields(table_slug)

            # Field selection
            fields_to_query = self._select_fields(query, table_fields)
            logger.debug(f"Selected fields to query: {fields_to_query.fields}")

            # SQL query generation
            gadm_level = gadm_levels[subtype]
            sql_query = self._generate_sql_query(
                query, fields_to_query, gadm_level, aoi, start_date, end_date
            )
            logger.debug(f"Generated SQL query: {sql_query.content}")

            # Execute query
            raw_data = self._execute_query(table_slug, sql_query.content)

            data_points = len(raw_data.get("data", []))
            logger.debug(f"Successfully pulled {data_points} data points.")

            return DataPullResult(
                success=True,
                data=raw_data,
                message=f"Successfully pulled data for {aoi_name}. Retrieved {data_points} data points to analyze.",
                data_points_count=data_points,
            )

        except Exception as e:
            error_msg = f"Failed to pull standard GFW data: {e}"
            logger.error(error_msg, exc_info=True)
            return DataPullResult(success=False, data={"data": []}, message=error_msg)

    def _determine_table_slug(self, table_name: str, subtype: str) -> str:
        """Determine the appropriate table slug based on subtype"""
        match subtype:
            case (
                "country"
                | "state-province"
                | "district-county"
                | "municipality"
                | "locality"
                | "neighbourhood"
            ):
                gadm_level = gadm_levels[subtype]
                return f"gadm__{table_name}__{gadm_level['name']}_change"
            case "kba":
                return f"kba__{table_name}_change"
            case "wdpa":
                return f"wdpa_protected_areas__{table_name}_change"
            case "landmark":
                return f"landmark__{table_name}_change"
            case _:
                logger.error(f"Unsupported subtype: {subtype}")
                raise ValueError(
                    f"Subtype: {subtype} does not match to any table in basemaps database."
                )

    def _select_fields(
        self, query: str, table_fields: FieldSelection
    ) -> FieldSelection:
        """Select appropriate fields based on user query"""
        FIELD_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
            [
                (
                    "user",
                    """
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
Select fields from the list of fields provided, based on the user's question and a csv defining the available fields to query. \n
Be mindful of fields that can help analyse data around specific date ranges, thresholds, etc. \n
User's question: {user_query} \n
CSV with available fields: {fields} \n
Return rows from the csv as the answer, where each row is formatted as 'name,data_type', and each row is separated by a newline \n character. Do not include any additional text
        """,
                )
            ]
        )

        logger.debug("Invoking field selection chain...")
        field_selection_chain = FIELD_SELECTION_PROMPT | SONNET.with_structured_output(
            FieldSelection
        )
        return field_selection_chain.invoke(
            {"user_query": query, "fields": table_fields.as_csv()}
        )

    def _generate_sql_query(
        self,
        query: str,
        fields_to_query: FieldSelection,
        gadm_level: Dict,
        aoi: Dict,
        start_date: str,
        end_date: str,
    ) -> Any:
        """Generate SQL query based on user query and selected fields"""
        SQL_QUERY_PROMPT = ChatPromptTemplate.from_messages(
            [
                (
                    "user",
                    """
            You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
            You will construct a SQL query to retrieve the requested data. You will be provided with the user's question and a list of fields to query, as pairs of field name and data type and a template for the SQL query with some information pre-filled. Do your best not to alter the existing elements of this template. \n

            User's question: {user_query} \n
            Start date: {start_date} \n
            End date: {end_date} \n
            Fields to query: \n{fields_to_query} \n
            Template: \n

            SELECT {gadm_level}, {{query_fields}} \n
            FROM data \n
            WHERE  ({location_filter}) AND {{filtering_fields}} \n
            GROUP BY {{grouping_field}} \n
            ORDER BY {{ordering_field}} \n
            \n

            Replace the placeholder {{query_fields}} with the fields from the list of the fields provided with any additional relevant SQL operation, appropriate for the field's data type, such as SUM() for numeric fields. \n
            Replace the placeholder {{filtering_fields}} with one or more filtering conditions, such as 'umd_tree_cover_density_2000__threshold' > 30, separated by AND. \n
            Replace the placeholder {{grouping_field}} with the field to group the data by, if appropriate. Otherwise you may choose to omit this portion of the query. \n
            Replace the placeholder {{ordering_field}} with the field to order the data by, if appropriate. Otherwise you may choose to omit this portion of the query. \n
            Make sure to enclose each of the query fields with double quotes (") in order to ensure that the SQL query is properly formatted. \n
            Return ONLY the raw SQL statement with no formatting, code blocks, or additional text. The output should be a plain SQL query that can be executed directly.
            """,
                )
            ]
        )

        logger.debug("Invoking SQL query generation chain...")
        sql_query_chain = SQL_QUERY_PROMPT | SONNET
        logger.info(f"aoi: {list(aoi.keys())}, gadm_level: {gadm_level}")
        location_filter = GadmId(gadm_id=aoi[gadm_level["col_name"]]).as_sql_filter()

        return sql_query_chain.invoke(
            {
                "user_query": query,
                "fields_to_query": fields_to_query.as_csv(),
                "gadm_level": gadm_level["name"],
                "location_filter": location_filter,
                "start_date": start_date,
                "end_date": end_date,
            }
        )

    def _execute_query(self, table_slug: str, sql_query: str) -> Dict:
        """Execute the SQL query against GFW Data API"""
        logger.debug("Executing query against GFW Data API...")
        return requests.post(
            f"{GFW_DATA_API_BASE_URL}/dataset/{table_slug}/latest/query/json",
            headers={"x-api-key": os.environ["GFW_DATA_API_KEY"]},
            json={"sql": sql_query},
        ).json()
