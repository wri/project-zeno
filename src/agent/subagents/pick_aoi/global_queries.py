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

from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE
from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import (
    AOI_SOURCE_ID_COLUMNS,
    SUBREGION_TO_SUBTYPE_MAPPING,
)

# Words that unambiguously mean "the whole world".
GLOBAL_TRIGGER_WORDS: frozenset[str] = frozenset(
    {"global", "world", "worldwide", "earth", "globe"}
)

# Display name for the AOI bundle when comparing all countries globally.
GLOBAL_AOI_SELECTION_NAME = "All countries in the world"


def is_global_request(places: list[str]) -> bool:
    """Return True if any place in *places* is a global synonym."""
    return any(
        word in p.lower().strip()
        for word in GLOBAL_TRIGGER_WORDS
        for p in places
    )


async def handle_global_request(
    subregion: str | None,
    tool_call_id: str | None,
    language: str = DEFAULT_LANGUAGE,
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
                        await t(
                            "pick_aoi.global_subregion_country_only",
                            language,
                        ),
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
        aoi[AOI_SOURCE_ID_COLUMNS[aoi["source"]]] = aoi["src_id"]

    return Command(
        update={
            "aoi_selection": {
                "name": GLOBAL_AOI_SELECTION_NAME,
                "aois": final_aois,
            },
            "messages": [
                ToolMessage(
                    "Selected all countries in the world",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


async def _query_all_countries() -> pd.DataFrame:
    """Return every country row from GADM. No spatial filter is necessary.

    ``NOT is_disputed`` replaces the ISO3-prefix regex on ``gadm_id``. Only GADM
    rows carry the flag, and the build sets it with that same regex, so the row
    set does not change.

    The query returns the world bbox for every country. This is intentional. A
    global comparison does not zoom to one country, so the query does not read
    the per-country bbox in ``aois``.
    """
    subtype = SUBREGION_TO_SUBTYPE_MAPPING["country"]
    sql_query = """
        SELECT name,
               subtype,
               source_id AS src_id,
               source    AS source,
               json_build_array(-180.0, -90.0, 180.0, 90.0) AS bbox
        FROM aois
        WHERE source = 'gadm'
          AND subtype = :subtype
          AND NOT is_disputed
          AND NOT is_deprecated
    """
    async with get_connection_from_pool() as conn:

        def _read(sync_conn):
            return pd.read_sql(
                text(sql_query), sync_conn, params={"subtype": subtype}
            )

        return await conn.run_sync(_read)
