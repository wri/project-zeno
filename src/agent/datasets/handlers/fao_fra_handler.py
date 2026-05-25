"""FAO FRA 2025 data source handler.

Plugs into `DataPullOrchestrator` like `AnalyticsHandler`. The orchestrator
already handles the upstream steps (`pick_aoi` resolves the country,
`pick_dataset` picks the FAO dataset + the right `context_layer`); this
handler just translates the chosen variable into a FAO API call and
returns the records inline.

Why not use the analytics-API contract:
- FAO is country-level only (the analytics API supports admin/KBA/WDPA/etc).
- FAO has fixed reporting years per variable (the analytics API is
  continuous time-series with custom date ranges).
- FAO responses are small (country × years × variables) and complete in
  one request — no async polling, no source_url indirection.
"""

from typing import Any, Dict, List, Optional

from src.agent.datasets.handlers.base import (
    DataPullResult,
    DataSourceHandler,
)
from src.agent.datasets.handlers.fao_fra_client import (
    FAOAPIError,
    FAODataNotFoundError,
    _build_source_url,
    fetch_fra_data,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Single source of truth for "which dataset does this handler claim".
# The handler matches on dataset_id, mirroring AnalyticsHandler.can_handle.
FAO_FRA_2025_DATASET_ID = 10


def _country_aois(aois: List[Dict]) -> List[Dict]:
    """Filter the AOI selection down to country-level GADM AOIs.

    FAO FRA 2025 carries national aggregates only. Sub-national AOIs
    (state/district/KBA/WDPA/custom) cannot be answered by this dataset
    — the caller should be redirected to the analytics pipeline.
    """
    return [
        a
        for a in aois
        if a.get("source") == "gadm" and a.get("subtype") == "country"
    ]


def _resolve_context_layer(
    dataset: Dict, value: Optional[str]
) -> Optional[Dict]:
    """Find the context_layer entry whose `value` matches the LLM-picked one."""
    if not value:
        return None
    for layer in dataset.get("context_layers") or []:
        if layer.get("value") == value:
            return layer
    return None


class FAOFRAHandler(DataSourceHandler):
    """Routes FAO FRA 2025 dataset requests to the FAO public API."""

    def can_handle(self, dataset: Any) -> bool:
        return dataset.get("dataset_id") == FAO_FRA_2025_DATASET_ID

    async def pull_data(
        self,
        query: str,
        dataset: Dict,
        start_date: str,
        end_date: str,
        change_over_time_query: bool,
        aois: List[Dict],
    ) -> DataPullResult:
        """Fetch FAO FRA data for the country AOIs + selected variable.

        The variable identity comes from `dataset["context_layer"]` —
        pick_dataset's LLM has already chosen one of the 21 layers from
        the FAO YAML, and pull_data passes the chosen `dataset` (with
        the resolved context_layer) through here.
        """
        context_layer_value = dataset.get("context_layer")
        layer = _resolve_context_layer(dataset, context_layer_value)
        if layer is None:
            return DataPullResult(
                success=False,
                data={"data": []},
                message=(
                    "FAO FRA: no context_layer selected. pick_dataset "
                    "must pick one of the 21 FAO variables (forest_area, "
                    "carbon_stock, ownership, …) before pull_data runs."
                ),
            )

        country_aois = _country_aois(aois)
        if not country_aois:
            return DataPullResult(
                success=False,
                data={"data": []},
                message=(
                    "FAO FRA 2025 only carries country-level statistics. "
                    "Resolve a country-level AOI (gadm subtype=country) "
                    "before pulling, or use a GFW dataset for "
                    "sub-national / remote-sensing analysis."
                ),
            )

        table = layer["fao_table"]
        variables_filter = layer.get("fao_variables") or []
        aoi_names = [a["name"] for a in country_aois]

        logger.info(
            f"FAO-FRA-HANDLER: variable={context_layer_value} "
            f"table={table} aois={aoi_names}"
        )

        records: list[dict] = []
        errors: list[str] = []
        for aoi in country_aois:
            iso3 = aoi["src_id"]
            try:
                rows = await fetch_fra_data(
                    iso3=iso3,
                    table=table,
                    variables=variables_filter,
                )
            except FAODataNotFoundError as exc:
                errors.append(f"{aoi['name']}: {exc}")
                continue
            except FAOAPIError as exc:
                errors.append(f"{aoi['name']}: {exc}")
                continue

            # Tag every record with the human-readable AOI name so chart
            # labels remain readable downstream (the FAO API only gives
            # us ISO3 codes).
            for row in rows:
                row["aoi_name"] = aoi["name"]
            records.extend(rows)

        if not records:
            error_text = " | ".join(errors) if errors else "No data returned."
            return DataPullResult(
                success=False,
                data={"data": []},
                message=f"FAO FRA: {error_text}",
            )

        message_parts = [
            f"Retrieved FAO FRA 2025 data for {', '.join(aoi_names)}: "
            f"{layer['description']}"
        ]
        if errors:
            message_parts.append(
                "Some AOIs had no data: " + " | ".join(errors)
            )

        # Use the first AOI's URL as a reference link; analyst keeps the
        # actual records inline since the FAO response is small.
        source_url = _build_source_url(country_aois[0]["src_id"], table)

        return DataPullResult(
            success=True,
            data={"data": records},
            message=" ".join(message_parts),
            data_points_count=len(records),
            analytics_api_url=source_url,
        )
