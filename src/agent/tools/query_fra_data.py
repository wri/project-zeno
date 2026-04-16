from typing import Annotated, Dict, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.tools.datasets_config import DATASETS
from src.agent.tools.fao_client import (
    FAOAPIError,
    FAODataNotFoundError,
    _build_source_url,
    fetch_fra_data,
)
from src.agent.tools.variable_map import VALID_VARIABLES, VARIABLE_MAP
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Load the FRA dataset config once at import time so generate_insights gets
# presentation_instructions, code_instructions, and cautions.
_FRA_DATASET_CONFIG = next(
    (d for d in DATASETS if d.get("dataset_name", "").startswith("FAO Global Forest")),
    None,
)


@tool("query_fra_data")
async def query_fra_data(
    query: str,
    variable: str,
    year: Optional[int] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
    state: Annotated[Dict, InjectedState] = None,
) -> Command:
    """Query the FAO Global Forest Resources Assessment (FRA) 2025 for national forest statistics.

    Use this tool when the user asks about country-reported, nationally-aggregated forest
    statistics. This is distinct from pull_data, which serves remote-sensing pixel data
    at sub-national resolution. Do NOT use this tool for sub-national analysis — use
    pull_data for that.

    This tool reads the country from the existing AOI selection (set by pick_aoi). You do
    NOT need to call pick_dataset before this tool.

    Supported variables:
    - forest_area: Total forest area by category (naturally regenerating, planted, primary)
    - forest_area_change: Annual net forest area change by period
    - forest_area_protected: Forest area within protected areas
    - permanent_forest_estate: Area designated as permanent forest estate
    - forest_characteristics: Forest composition (mangroves, bamboo, rubber, etc.)
    - growing_stock: Total growing stock volume
    - growing_stock_per_ha: Average growing stock per hectare
    - growing_stock_composition: Growing stock by species/genus composition
    - biomass: Total biomass stock
    - biomass_per_ha: Average biomass per hectare
    - carbon_stock: Total carbon stock across all five pools
    - carbon_stock_by_pool: Carbon stock broken down by pool
    - carbon_stock_soil_depth: Soil carbon by depth layer
    - management_objectives: Forest area by designated management objective
    - designated_management: Total area with a designated management objective
    - management_rights: Forest area by holder of management rights
    - ownership: Forest area by ownership category
    - disturbances: Area affected by insects, disease, severe weather (2002–2020)
    - fire: Forest area affected by fire (2007–2019)
    - degraded_forest: Area of degraded forest (national definitions)
    - forest_restoration: Area under restoration/reforestation

    Args:
        query: The user's original question, for context.
        variable: FRA variable name (see supported variables above).
        year: Optional reporting year (1990, 2000, 2010, 2015, 2020, or 2025).
              Defaults to all available years.
    """
    if variable not in VARIABLE_MAP:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            f"'{variable}' is not a recognised FRA variable. "
                            f"Valid options are: {', '.join(VALID_VARIABLES)}. "
                            "You can browse all variables at https://fra-data.fao.org."
                        ),
                        tool_call_id=tool_call_id,
                        status="success",
                        response_metadata={"msg_type": "human_feedback"},
                    )
                ]
            }
        )

    aois = state["aoi_selection"]["aois"]
    aoi_names = [a["name"] for a in aois]
    var_config = VARIABLE_MAP[variable]
    table = var_config["table"]
    variables_filter = var_config["variables"]
    unit = var_config["unit"]

    logger.info(
        f"QUERY-FRA-DATA: variable={variable} table={table} year={year} aois={aoi_names}"
    )

    all_records: list[dict] = []
    errors: list[str] = []

    for aoi in aois:
        iso3 = aoi["src_id"]
        try:
            records = await fetch_fra_data(
                iso3=iso3,
                table=table,
                variables=variables_filter,
                year=year,
            )
            # Tag each record with the AOI name for downstream chart rendering.
            for r in records:
                r["aoi_name"] = aoi["name"]
            all_records.extend(records)
        except FAODataNotFoundError as exc:
            errors.append(str(exc))
        except FAOAPIError as exc:
            errors.append(str(exc))

    if not all_records:
        error_text = " | ".join(errors) if errors else "No data returned."
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=error_text,
                        tool_call_id=tool_call_id,
                        status="success",
                        response_metadata={"msg_type": "human_feedback"},
                    )
                ]
            }
        )

    year_label = str(year) if year else "all years"
    source_url = _build_source_url(aois[0]["src_id"], table)

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

    update: dict = {
        "statistics": [
            {
                "dataset_name": f"FAO FRA 2025 — {var_config['description']} ({unit})",
                "start_date": "1990-01-01",
                "end_date": "2025-12-31",
                "source_url": source_url,
                "data": all_records,
                "aoi_names": aoi_names,
            }
        ],
        "messages": [tool_message],
    }

    # Inject FRA dataset config so generate_insights gets presentation/code instructions.
    if _FRA_DATASET_CONFIG is not None:
        update["dataset"] = _FRA_DATASET_CONFIG

    return Command(update=update)
