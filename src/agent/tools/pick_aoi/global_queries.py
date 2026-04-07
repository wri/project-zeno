"""Global (world-wide) query handling for the pick_aoi tool.

When a user asks about "the world" or "globally", there is no meaningful single
geometry to look up — the intent is always to get *all* areas of a given subtype.
This module handles that case entirely in code, bypassing the spatial database
search used for named places.  No synthetic row in the DB is needed.
"""

import pandas as pd
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from sqlalchemy import text

from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import (
    GADM_TABLE,
    KBA_TABLE,
    LANDMARK_TABLE,
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
    WDPA_TABLE,
)

# Words that unambiguously mean "the whole world".
GLOBAL_TRIGGER_WORDS: frozenset[str] = frozenset(
    {"global", "world", "worldwide", "earth", "globe"}
)

# Display name used in selection_name when the parent scope is the whole world.
GLOBAL_DISPLAY_NAME = "Global"


def is_global_request(places: list[str]) -> bool:
    """Return True if any place in *places* is a global synonym."""
    return any(p.lower().strip() in GLOBAL_TRIGGER_WORDS for p in places)


async def query_global_subregions(subregion_name: str) -> pd.DataFrame:
    """Return every area of *subregion_name* type in the database.

    No spatial filter is applied — for a global scope it would be a no-op
    (every country is covered by the world bounding box).  We simply query
    by subtype, which is both simpler and faster.

    Args:
        subregion_name: One of the subregion keys accepted by pick_aoi
            (e.g. "country", "state", "kba", "wdpa", "landmark").

    Returns:
        DataFrame with columns: name, subtype, src_id, source.

    Raises:
        ValueError: If *subregion_name* is not recognised.
    """
    match subregion_name:
        case (
            "country"
            | "state"
            | "district"
            | "municipality"
            | "locality"
            | "neighbourhood"
        ):
            table_name = GADM_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING[subregion_name]
            source = "gadm"
            src_id_field = SOURCE_ID_MAPPING["gadm"]["id_column"]
        case "kba":
            table_name = KBA_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["kba"]
            source = "kba"
            src_id_field = SOURCE_ID_MAPPING["kba"]["id_column"]
        case "wdpa":
            table_name = WDPA_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["wdpa"]
            source = "wdpa"
            src_id_field = SOURCE_ID_MAPPING["wdpa"]["id_column"]
        case "landmark":
            table_name = LANDMARK_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["landmark"]
            source = "landmark"
            src_id_field = SOURCE_ID_MAPPING["landmark"]["id_column"]
        case _:
            raise ValueError(
                f"Unknown subregion '{subregion_name}' for global query."
            )

    sql_query = f"""
        SELECT name,
               subtype,
               CAST({src_id_field} AS TEXT) AS src_id,
               :source                       AS source
        FROM {table_name}
        WHERE subtype = :subtype
    """

    async with get_connection_from_pool() as conn:

        def _read(sync_conn):
            return pd.read_sql(
                text(sql_query),
                sync_conn,
                params={"subtype": subtype, "source": source},
            )

        return await conn.run_sync(_read)


async def handle_global_request(
    subregion: str | None, tool_call_id: str
) -> Command:
    """Entry point called by pick_aoi when a global place is detected.

    Validates that subregion is 'country' (the only supported scope for global
    queries), fetches all countries, and returns a ready-to-return Command.
    """
    if subregion != "country":
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Global queries only support subregion='country'. "
                        "Please set subregion='country' to compare across all countries.",
                        tool_call_id=tool_call_id,
                        status="success",
                        response_metadata={"msg_type": "human_feedback"},
                    )
                ],
            },
        )

    df = await _query_all_countries()
    final_aois = df.to_dict(orient="records")
    for aoi in final_aois:
        aoi[SOURCE_ID_MAPPING[aoi["source"]]["id_column"]] = aoi["src_id"]

    return Command(
        update={
            "aoi_selection": {
                "name": "All countries in the world",
                "aois": final_aois,
            },
            "aoi": final_aois[0],
            "subtype": final_aois[0]["subtype"],
            "messages": [
                ToolMessage(
                    "Selected all countries in the world",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


async def _query_all_countries() -> pd.DataFrame:
    """Return every country row from GADM — no spatial filter needed."""
    src_id_field = SOURCE_ID_MAPPING["gadm"]["id_column"]
    subtype = SUBREGION_TO_SUBTYPE_MAPPING["country"]
    sql_query = f"""
        SELECT name,
               subtype,
               CAST({src_id_field} AS TEXT) AS src_id,
               'gadm'                        AS source
        FROM {GADM_TABLE}
        WHERE subtype = :subtype
    """
    async with get_connection_from_pool() as conn:

        def _read(sync_conn):
            return pd.read_sql(
                text(sql_query), sync_conn, params={"subtype": subtype}
            )

        return await conn.run_sync(_read)
