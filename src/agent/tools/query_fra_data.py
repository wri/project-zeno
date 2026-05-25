"""Primitive tool that fetches FAO FRA 2025 statistics.

Sits in the orchestrator's tool list alongside `pull_data`. Bypasses
`pick_dataset` deliberately — the FAO YAML is in `datasets/catalog/` so
`generate_insights` still receives FAO-specific `presentation_instructions`
/ `code_instructions` / `cautions`, but it gets there via `state["dataset"]`
that this tool writes itself.

This is a primitive (no internal LLM step). Variable selection happens in the
`pick_fra_variable` subagent earlier in the recipe; this tool only validates
that the variable name is known and forwards it to the FAO client.
"""

from typing import Annotated, Dict, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers import fao_fra_client
from src.agent.datasets.handlers.fao_fra_client import (
    FAOAPIError,
    FAODataNotFoundError,
)
from src.agent.subagents.pick_fra_variable.variable_map import (
    VALID_VARIABLES,
    VARIABLE_MAP,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Load the FAO FRA dataset config once at import time so generate_insights
# receives presentation_instructions / code_instructions / cautions.
_FRA_DATASET_CONFIG: Optional[dict] = next(
    (
        d
        for d in DATASETS
        if d.get("dataset_name", "").startswith(
            "FAO Global Forest Resources Assessment"
        )
    ),
    None,
)


def _human_feedback_message(
    content: str, tool_call_id: Optional[str]
) -> ToolMessage:
    """Build a recoverable ToolMessage — surfaces to the user but not as
    an agent error, so the orchestrator can keep the conversation going."""
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        status="success",
        response_metadata={"msg_type": "human_feedback"},
    )


def _country_aois(state: Dict) -> list[dict]:
    """Filter the current AOI selection down to country-level GADM AOIs.

    FAO FRA 2025 only carries country-level statistics. If pick_aoi
    resolved to a sub-national area (state, district, KBA, …), this
    returns an empty list and the caller redirects.
    """
    selection = state.get("aoi_selection") or {}
    aois = selection.get("aois") or []
    return [
        a
        for a in aois
        if a.get("source") == "gadm" and a.get("subtype") == "country"
    ]


@tool("query_fra_data")
async def query_fra_data(
    variable: str,
    state: Annotated[Dict, InjectedState],
    year: Optional[int] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Fetch FAO FRA 2025 statistics for the variable picked by
    `pick_fra_variable`.

    Country-level data only. Reads ISO3 country codes from the AOI selection
    set by `pick_aoi` (gadm subtype=country). If the AOI is sub-national,
    the tool returns a redirect message — do not retry with a different
    `variable`; instead call `pick_aoi` to resolve a country, or fall back
    to the GFW pipeline via the `analyze` skill.

    Args:
        variable: One of the FAO FRA variable names (e.g. "forest_area",
            "carbon_stock", "ownership"). Pass the exact value
            `pick_fra_variable` selected.
        year: Optional FRA reporting year (1990, 2000, 2010, 2015, 2020,
            or 2025). Omit to return all available years.
    """
    if variable not in VARIABLE_MAP:
        return Command(
            update={
                "messages": [
                    _human_feedback_message(
                        f"'{variable}' is not a recognised FAO FRA variable."
                        f" Valid options: {', '.join(VALID_VARIABLES)}. "
                        "Call pick_fra_variable to choose one.",
                        tool_call_id,
                    )
                ]
            }
        )

    aois = _country_aois(state)
    if not aois:
        return Command(
            update={
                "messages": [
                    _human_feedback_message(
                        "FAO FRA 2025 only carries country-level statistics. "
                        "Resolve a country first (call pick_aoi with the "
                        "country name), or use the `analyze` skill for "
                        "sub-national / remote-sensing analysis.",
                        tool_call_id,
                    )
                ]
            }
        )

    aoi_names = [a["name"] for a in aois]
    var_config = VARIABLE_MAP[variable]
    table = var_config["table"]
    variables_filter = var_config["variables"]
    unit = var_config["unit"]

    logger.info(
        f"QUERY-FRA-DATA: variable={variable} table={table} "
        f"year={year} aois={aoi_names}"
    )

    all_records: list[dict] = []
    errors: list[str] = []
    for aoi in aois:
        iso3 = aoi["src_id"]
        try:
            # Call via the module so tests can monkeypatch
            # `fao_fra_client.fetch_fra_data` at one unambiguous location.
            records = await fao_fra_client.fetch_fra_data(
                iso3=iso3,
                table=table,
                variables=variables_filter,
                year=year,
            )
        except FAODataNotFoundError as exc:
            errors.append(str(exc))
            continue
        except FAOAPIError as exc:
            errors.append(str(exc))
            continue

        for rec in records:
            rec["aoi_name"] = aoi["name"]
        all_records.extend(records)

    if not all_records:
        error_text = " | ".join(errors) if errors else "No data returned."
        return Command(
            update={
                "messages": [_human_feedback_message(error_text, tool_call_id)]
            }
        )

    year_label = str(year) if year else "all reporting years"
    source_url = fao_fra_client._build_source_url(aois[0]["src_id"], table)

    tool_message_parts = [
        f"Retrieved FAO FRA 2025 data for {', '.join(aoi_names)}: "
        f"{var_config['description']} ({year_label})."
    ]
    if errors:
        tool_message_parts.append(
            "Note: some AOIs had no data: " + " | ".join(errors)
        )

    tool_message = ToolMessage(
        content=" ".join(tool_message_parts),
        tool_call_id=tool_call_id,
    )

    statistics_entry = {
        "dataset_name": (
            f"FAO FRA 2025 — {var_config['description']} ({unit})"
        ),
        "start_date": "1990-01-01",
        "end_date": "2025-12-31",
        "source_url": source_url,
        # FAO responses are small (country × years × variables); keep
        # data inline so the analyst's inline-data path handles it
        # directly without a second fetch.
        "data": all_records,
        "aoi_names": aoi_names,
        "parameters": None,
        "context_layer": None,
    }

    update: dict = {
        "statistics": [statistics_entry],
        "messages": [tool_message],
    }

    if _FRA_DATASET_CONFIG is not None:
        update["dataset"] = _FRA_DATASET_CONFIG

    return Command(update=update)
