"""Global (world-wide) query handling for the pick_aoi tool.

When a user asks about "the world" or "globally", the intent is always to
compare all countries.  This module handles that case entirely in code,
bypassing the spatial DB lookup used for named places.  No synthetic row
in the DB is needed.
"""

import pandas as pd
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from sqlalchemy import text

from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import (
    GADM_TABLE,
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
)

# Words that unambiguously mean "the whole world".
GLOBAL_TRIGGER_WORDS: frozenset[str] = frozenset(
    {"global", "world", "worldwide", "earth", "globe"}
)


def is_global_request(places: list[str]) -> bool:
    """Return True if any place in *places* is a global synonym."""
    return any(p.lower().strip() in GLOBAL_TRIGGER_WORDS for p in places)


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
