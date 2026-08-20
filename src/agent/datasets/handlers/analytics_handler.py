import asyncio
import os
from typing import Any, Dict

import httpx
from pydantic import BaseModel

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.base import (
    DataPullResult,
    DataSourceHandler,
)
from src.shared.geocoding_helpers import (
    format_id,
    get_geometry_data,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class BooleanResponse(BaseModel):
    """Response model for boolean queries"""

    result: bool


ADMIN_SUBTYPES = (
    "country",
    "state-province",
    "district-county",
    "municipality",
    "locality",
    "neighbourhood",
)
SLUC_GADM_LEVELS = ["country", "state-province", "district-county"]

SLUC_CROPS = [
    "Banana",
    "Barley",
    "Bean",
    "Cassava",
    "Chickpea",
    "Coconut",
    "Cocoa",
    "Arabica Coffee",
    "Robusta Coffee",
    "Cotton",
    "Cowpea",
    "Groundnut",
    "Lentil",
    "Maize",
    "Pearl Millet",
    "Small Millet",
    "Oil Palm",
    "Pigeon Pea",
    "Plantain",
    "Potato",
    "Rapeseed",
    "Rice",
    "Sesame Seed",
    "Sorghum",
    "Soybean",
    "Sugarbeet",
    "Sugarcane",
    "Sunflower",
    "Sweet Potato",
    "Tea",
    "Tobacco",
    "Wheat",
    "Yams",
    "Other Cereals",
    "Other Fibre Crops",
    "Other Oil Crops",
    "Other Pulses",
    "Other Roots",
    "Rest of Crops",
    "Temperate Fruit",
    "Tropical Fruit",
    "Vegetables",
]

SLUC_GAS_TYPES = ["CO2e", "CO2", "CH4", "N2O"]

# Add dataset-specific parameters
DIST_ALERT_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"]
    == "Global all ecosystem disturbance alerts (DIST-ALERT)"
][0]
INTEGRATED_ALERTS_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Integrated alerts"
][0]
NATURAL_LANDS_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "SBTN Natural Lands Map"
][0]
LAND_COVER_CHANGE_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Global land cover"
][0]
GRASSLANDS_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Global natural/semi-natural grassland extent"
][0]
TREE_COVER_LOSS_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Tree cover loss"
][0]
TREE_COVER_GAIN_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Tree cover gain"
][0]
FOREST_CARBON_FLUX_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Forest greenhouse gas net flux"
][0]
TREE_COVER_ID = [
    ds["dataset_id"] for ds in DATASETS if ds["dataset_name"] == "Tree cover"
][0]
TREE_COVER_LOSS_BY_DRIVER_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Tree cover loss by dominant driver"
][0]
SLUC_EMISSION_FACTORS_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"]
    == "Deforestation (sLUC) Emission Factors by Agricultural Crop"
][0]
TREE_COVER_LOSS_BY_FIRES_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Tree cover loss due to fires"
][0]
LAND_GHG_INVENTORY_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Land GHG Monitoring System (LGMS)"
][0]


def _first_list_len(section: Any) -> int:
    if isinstance(section, dict):
        for value in section.values():
            if isinstance(value, list):
                return len(value)
    return 0


# Land GHG Monitoring System (LGMS) returns a per-section result (vegetation,
# mineral_soil, organic_soil, agriculture). Merge it into one flat table with
# unified `category` / `class` dimensions so it flows through the normal
# analysis pipeline as a single table.
LGMS_SECTION_CATEGORY = {
    "vegetation": "vegetation",
    "mineral_soil": "soil",
    "organic_soil": "soil",
    "agriculture": "agriculture",
}
LGMS_MERGED_COLUMNS = [
    "aoi_id",
    "aoi_type",
    "category",
    "class",
    "year",
    "gross_emissions_MgCO2e",
    "gross_removals_MgCO2",
    "net_flux_MgCO2e",
    "area_ha",
]
LGMS_METRIC_COLUMNS = (
    "gross_emissions_MgCO2e",
    "gross_removals_MgCO2",
    "net_flux_MgCO2e",
    "area_ha",
)


def _lgms_row_class(section_name: str, row: dict) -> Any:
    """The merged `class` value: the vegetation land-state verbatim, the
    crop/livestock category for agriculture, or the section name itself for
    soil ('mineral_soil'/'organic_soil' — already the exact class name)."""
    if section_name == "vegetation":
        return row.get("land_state_class")
    if section_name == "agriculture":
        return row.get("category")
    if section_name in ("mineral_soil", "organic_soil"):
        return section_name
    return None


def merge_lgms_sections(raw_data: dict) -> dict:
    """Flatten LGMS's per-section result (vegetation, mineral_soil,
    organic_soil, agriculture) into one column-oriented table with unified
    `category` / `class` columns; metrics absent from a section are filled with
    None. Applied wherever the LGMS result is read (see LAND_GHG_INVENTORY_ID
    checks in the handler's process-response and the analyst's re-fetch)."""
    merged: dict[str, list] = {col: [] for col in LGMS_MERGED_COLUMNS}
    for section_name, columns in raw_data.items():
        keys = list(columns)
        count = len(columns[keys[0]]) if keys else 0
        for i in range(count):
            row = {key: columns[key][i] for key in keys}
            merged["aoi_id"].append(row.get("aoi_id"))
            merged["aoi_type"].append(row.get("aoi_type"))
            merged["category"].append(
                LGMS_SECTION_CATEGORY.get(section_name, section_name)
            )
            merged["class"].append(_lgms_row_class(section_name, row))
            merged["year"].append(row.get("year"))
            for metric in LGMS_METRIC_COLUMNS:
                merged[metric].append(row.get(metric))
    return merged


def _count_and_enrich(raw_data: Any, aois: list[dict]) -> tuple[Any, int]:
    """Count data points and add AOI names (by ``aoi_id``) to a flat result."""
    count = _first_list_len(raw_data) if isinstance(raw_data, dict) else 0
    if isinstance(raw_data, dict) and "aoi_id" in raw_data:
        aois_id_to_name = {
            format_id(item["src_id"]): item.get("name", item["src_id"]).split(
                ","
            )[0]
            for item in aois
        }
        raw_data["name"] = [aois_id_to_name[idx] for idx in raw_data["aoi_id"]]
    return raw_data, count


def analytics_api_headers() -> dict[str, str]:
    """Headers for every request to the analytics API — Bearer auth
    (WRI_BEARER_TOKEN, now required) plus the environment selector. Read at
    call time so the token isn't captured at import."""
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-environment": (
            "production"
            if os.getenv("GNW_STAGE", "production").strip().lower()
            == "production"
            else "staging"
        ),
        "Authorization": f"Bearer {os.getenv('WRI_BEARER_TOKEN', '')}",
    }


class AnalyticsHandler(DataSourceHandler):
    """Generalized handler for GFW Analytics API endpoints"""

    def __init__(self) -> None:
        # Base URL is env-configurable so evals/local runs can target a
        # non-production analytics API (e.g. http://localhost:8001).
        self.BASE_URL = os.getenv(
            "ANALYTICS_API_BASE_URL",
            "https://analytics.globalnaturewatch.org",
        )

    def can_handle(self, dataset: Any) -> bool:
        """Check if this handler can process the given dataset"""
        return dataset.get("dataset_id") in [
            DIST_ALERT_ID,
            INTEGRATED_ALERTS_ID,
            NATURAL_LANDS_ID,
            LAND_COVER_CHANGE_ID,
            GRASSLANDS_ID,
            TREE_COVER_LOSS_ID,
            TREE_COVER_GAIN_ID,
            FOREST_CARBON_FLUX_ID,
            TREE_COVER_ID,
            TREE_COVER_LOSS_BY_DRIVER_ID,
            SLUC_EMISSION_FACTORS_ID,
            TREE_COVER_LOSS_BY_FIRES_ID,
            LAND_GHG_INVENTORY_ID,
        ]

    def _get_aoi_type(self, aoi: Dict) -> dict[str, str]:
        """Get the type of the AOI"""

        if aoi["subtype"] in ADMIN_SUBTYPES:
            aoi_type = "admin"
        elif aoi["subtype"] == "key-biodiversity-area":
            aoi_type = "key_biodiversity_area"
        elif aoi["subtype"] == "indigenous-and-community-land":
            aoi_type = "indigenous_land"
        elif aoi["subtype"] == "protected-area":
            aoi_type = "protected_area"
        elif aoi["subtype"] == "custom-area":
            # See DistAlertsAnalyticsIn schema
            # in https://analytics.globalnaturewatch.org/docs
            aoi_type = "feature_collection"
        else:
            raise ValueError(f"Unknown AOI subtype: {aoi['subtype']}")

        if aoi_type == "admin":
            return {
                "type": "admin",
                "provider": "gadm",
                "version": "4.1",
            }
        else:
            return {"type": aoi_type}

    async def _build_payload(
        self,
        dataset: dict,
        aois: list[dict],
        start_date: str,
        end_date: str,
    ) -> Dict:
        """Build the API payload based on dataset type"""
        # Base payload structure common to all endpoints
        aoi_type = self._get_aoi_type(aois[0])
        # Fix for GADM IDs which come with a _1 suffix
        for aoi in aois:
            if aoi["src_id"][-2:] in ["_1", "_2", "_3", "_4", "_5"]:
                aoi["src_id"] = aoi["src_id"][:-2]

        # Handle custom areas differently - they need a feature collection
        if aoi_type["type"] == "feature_collection":
            features = []
            for aoi in aois:
                geometry_data = await get_geometry_data(
                    "custom", aoi["src_id"]
                )
                if not geometry_data:
                    raise ValueError(f"Custom area not found: {aoi['src_id']}")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geometry_data["geometry"],
                        "properties": {
                            "name": geometry_data["name"],
                            "id": geometry_data["src_id"],
                        },
                    }
                )

            feature_collection = {
                "type": "FeatureCollection",
                "features": features,
            }

            base_payload = {
                "aoi": {
                    "type": aoi_type["type"],
                    "feature_collection": feature_collection,
                }
            }
        else:
            aoi_ids = [format_id(aoi["src_id"]) for aoi in aois]
            base_payload = {
                "aoi": {
                    "type": aoi_type["type"],
                    "ids": aoi_ids,
                }
            }

        logger.debug(f"dataset: {dataset}")

        payload: dict[str, Any]
        if dataset.get("dataset_id") == DIST_ALERT_ID:
            payload = {
                **base_payload,
                "start_date": start_date,
                "end_date": end_date,
                "intersections": (
                    [dataset["context_layer"]]
                    if dataset.get("context_layer")
                    else []
                ),
            }

        elif dataset.get("dataset_id") == INTEGRATED_ALERTS_ID:
            # Integrated Alerts has no intersections; it takes full dates only.
            payload = {
                **base_payload,
                "start_date": start_date,
                "end_date": end_date,
            }

        elif dataset.get("dataset_id") in [
            NATURAL_LANDS_ID,
            LAND_COVER_CHANGE_ID,
        ]:
            # Natural lands and grasslands don't require date ranges
            payload = base_payload

        elif dataset.get("dataset_id") == GRASSLANDS_ID:
            payload = {
                **base_payload,
                "start_year": start_date[:4],  # Extract year from YYYY-MM-DD
                "end_year": end_date[:4],
            }
        elif dataset.get("dataset_id") in [
            TREE_COVER_LOSS_ID,
            TREE_COVER_LOSS_BY_DRIVER_ID,
            TREE_COVER_LOSS_BY_FIRES_ID,
        ]:
            forest_filter = None

            if dataset.get("context_layer") == "primary_forest":
                forest_filter = "primary_forest"

            elif dataset.get("context_layer") == "intact_forest":
                forest_filter = "intact_forest"
            intersections = []
            if dataset.get("dataset_id") == TREE_COVER_LOSS_BY_DRIVER_ID:
                intersections = ["driver"]
            if dataset.get("dataset_id") == TREE_COVER_LOSS_BY_FIRES_ID:
                intersections = ["fire"]

            payload = {
                **base_payload,
                "start_year": start_date[:4],
                "end_year": end_date[:4],
                "forest_filter": forest_filter,
                "intersections": intersections,
            }
        elif dataset.get("dataset_id") == TREE_COVER_GAIN_ID:
            # Tree cover gain is only available in 5-year intervals
            start_year = int(start_date[:4]) - int(start_date[:4]) % 5
            end_year = int(end_date[:4]) - int(end_date[:4]) % 5
            if start_year == end_year:
                end_year += 5

            forest_filter = None
            if dataset.get("context_layer") == "primary_forest":
                forest_filter = "primary_forest"

            payload = {
                **base_payload,
                "start_year": str(max(2000, start_year)),
                "end_year": str(max(2005, end_year)),
                "forest_filter": forest_filter,
            }
        elif dataset.get("dataset_id") == FOREST_CARBON_FLUX_ID:
            payload = {
                **base_payload,
            }
        elif dataset.get("dataset_id") == LAND_GHG_INVENTORY_ID:
            # AOI only — the endpoint returns the full series (vegetation by
            # year + agriculture snapshot) with no date filter.
            payload = {
                **base_payload,
            }
        elif dataset.get("dataset_id") == TREE_COVER_ID:
            forest_filter = None
            if dataset.get("context_layer") == "primary_forest":
                forest_filter = "primary_forest"

            payload = {
                **base_payload,
                "forest_filter": forest_filter,
            }
        elif dataset.get("dataset_id") == SLUC_EMISSION_FACTORS_ID:
            payload = {
                **base_payload,
                "gas_types": SLUC_GAS_TYPES,
                "crop_types": SLUC_CROPS,
                "start_year": start_date[:4],
                "end_year": end_date[:4],
            }
        else:
            raise ValueError(
                f"Unknown dataset ID: {dataset.get('dataset_id')}"
            )

        if dataset.get("dataset_id") in [
            TREE_COVER_LOSS_ID,
            TREE_COVER_ID,
            TREE_COVER_LOSS_BY_DRIVER_ID,
            TREE_COVER_LOSS_BY_FIRES_ID,
            FOREST_CARBON_FLUX_ID,
        ]:
            canopy_cover: int = 30
            params = dataset.get("parameters")
            if params is not None:
                for param in params:
                    if param["name"] == "canopy_cover":
                        canopy_cover = int(max(param["values"]))

            payload = {**payload, "canopy_cover": canopy_cover}

        return payload

    async def _poll_for_completion(
        self,
        endpoint_url: str,
        payload: Dict,
        max_retries: int = 30,
    ) -> Dict | str:
        """Poll the API until the request is completed or max retries exceeded."""
        result = {}
        for attempt in range(max_retries):
            logger.info(f"Polling attempt {attempt + 1}/{max_retries}")

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        endpoint_url,
                        headers=analytics_api_headers(),
                        json=payload,
                    )
                if response.status_code >= 400:
                    logger.warning(
                        f"Poll attempt {attempt + 1} failed with status {response.status_code}"
                    )
                    continue

                result = response.json()
                status = result.get("status")
                logger.info(
                    f"Poll attempt {attempt + 1}, Status = {status}, Message = {result.get('message')}"
                )

                if status in ["success", "saved"]:
                    logger.info(
                        f"Request completed successfully after {attempt + 1} polling attempts"
                    )
                    return result
                elif status in ["failed", "error"]:
                    msg = f"Request failed with status: {status}"
                    logger.error(msg)
                    return msg

                retry_after = float(response.headers.get("Retry-After", 1))
                await asyncio.sleep(retry_after)

            except Exception as e:
                logger.warning(
                    f"Poll attempt {attempt + 1} failed with error: {e}"
                )
                continue

        msg = f"Max polling attempts ({max_retries}) exceeded for {result.get('data', {}).get('link', 'unknown url')}"
        logger.warning(msg)
        return msg

    async def _process_response_data(
        self,
        result: Dict,
        aois: list[dict],
        dataset: dict,
    ) -> tuple[Any, int, str, str]:
        """Process the response data based on dataset type."""

        if "data" not in result:
            raise ValueError(f"Response missing 'data' key: {result}")

        data_section = result["data"]

        if "link" not in data_section:
            raise ValueError(
                f"Data response missing 'link' key: {data_section}"
            )

        download_link = data_section["link"]
        async with httpx.AsyncClient() as client:
            response = await client.get(
                download_link, headers=analytics_api_headers()
            )
            data = response.json()

        if "data" not in data:
            raise ValueError(
                f"Response missing 'result' key in response: {data}"
            )
        if "result" not in data["data"]:
            raise ValueError(
                f"Response missing 'result' key in data section: {data['data']}"
            )

        raw_data = data["data"]["result"]

        # LGMS returns a per-section result; flatten it into one table so it
        # flows through the normal single-table analysis path.
        if dataset.get("dataset_id") == LAND_GHG_INVENTORY_ID:
            raw_data = merge_lgms_sections(raw_data)
        raw_data, data_points_count = _count_and_enrich(raw_data, aois)
        message_detail = f"Found {data_points_count} data points"
        analytics_url = result["data"]["link"]

        return raw_data, data_points_count, message_detail, analytics_url

    async def pull_data(
        self,
        query: str,
        dataset: dict,
        start_date: str,
        end_date: str,
        change_over_time_query: bool,
        aois: list[dict],
    ) -> DataPullResult:
        # SLUC emission factors are only available for GADM levels 0, 1, and 2
        if (
            dataset.get("dataset_id") == SLUC_EMISSION_FACTORS_ID
            and aois[0]["subtype"] not in SLUC_GADM_LEVELS
        ):
            msg = f"Can not pull data for aoi {aois[0].get('name', '')}. Subtype {aois[0]['subtype']} not supported for SLUC emission factors data, it is only available for GADM admin areas."
            return DataPullResult(
                success=False,
                data=None,
                message=msg,
                data_points_count=0,
                analytics_api_url=None,
            )
        try:
            # Hydrate selected dataset with full metadata
            dataset_full = [
                ds
                for ds in DATASETS
                if ds["dataset_id"] == dataset.get("dataset_id")
            ]
            dataset = dataset_full[0] | dataset

            # Get the appropriate endpoint URL
            if (
                dataset.get("dataset_id") == LAND_COVER_CHANGE_ID
                and not change_over_time_query
            ):
                endpoint_url = (
                    self.BASE_URL
                    + "/v0/land_change/land_cover_composition/analytics"
                )
            else:
                endpoint_url = (
                    self.BASE_URL + dataset["analytics_api_endpoint"]
                )

            # Build the payload based on dataset type
            payload = await self._build_payload(
                dataset, aois, start_date, end_date
            )

            headers = analytics_api_headers()
            redacted_headers = {**headers, "Authorization": "Bearer ***"}
            # Debug logging for payload (bearer token redacted above)
            logger.info(
                f"Analytics API Request - Dataset: {dataset.get('dataset_name')}"
            )
            logger.info(f"Analytics API Request - URL: {endpoint_url}")
            logger.info(f"Analytics API Request - Headers: {redacted_headers}")
            logger.info(f"Analytics API Request - Payload: {payload}")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint_url, headers=headers, json=payload
                )

            # Debug logging for response
            logger.info(
                f"Analytics API Response - Status Code: {response.status_code}"
            )
            logger.info(
                f"Analytics API Response - Headers: {dict(response.headers)}"
            )
            logger.info(f"Analytics API Response - Raw Text: {response.text}")

            try:
                result = response.json()
                logger.info(f"Analytics API Response - Parsed JSON: {result}")
            except Exception as json_error:
                error_msg = f"Failed to parse JSON response from Analytics API. Status: {response.status_code}, Text: {response.text}, Error: {json_error}"
                logger.error(error_msg)
                return DataPullResult(
                    success=False,
                    data=None,
                    message=error_msg,
                    analytics_api_url=None,
                )

            # Check if status key exists before accessing it
            if "status" not in result:
                error_msg = f"Analytics API response missing 'status' key. Available keys: {list(result.keys())}, Full response: {result}"
                logger.error(error_msg)
                return DataPullResult(
                    success=False,
                    data=None,
                    message=error_msg,
                    analytics_api_url=None,
                )

            # Handle pending status with retry logic
            aoi_names = ", ".join(
                [aoi.get("name", aoi["src_id"]) for aoi in aois]
            )
            if result["status"] == "pending":
                logger.info(
                    "Analytics request is pending, will retry with polling..."
                )
                result = await self._poll_for_completion(
                    endpoint_url, payload, max_retries=10
                )
                if isinstance(result, str):
                    error_msg = f"Failed to get completed result after polling for {aoi_names}. Reason: {result}"
                    logger.error(error_msg)
                    return DataPullResult(
                        success=False,
                        data=None,
                        message=error_msg,
                        data_points_count=0,
                        analytics_api_url=None,
                    )
                else:
                    (
                        raw_data,
                        data_points_count,
                        message_detail,
                        analytics_url,
                    ) = await self._process_response_data(
                        result, aois, dataset
                    )
                    return DataPullResult(
                        success=True,
                        data=raw_data,
                        message=f"Successfully pulled {dataset.get('dataset_name')} data from GFW Analytics for {aoi_names}. {message_detail}.",
                        data_points_count=data_points_count,
                        analytics_api_url=analytics_url,
                    )
            elif result["status"] in ["success", "saved"]:
                (
                    raw_data,
                    data_points_count,
                    message_detail,
                    analytics_url,
                ) = await self._process_response_data(result, aois, dataset)
                return DataPullResult(
                    success=True,
                    data=raw_data,
                    message=f"Successfully pulled {dataset.get('dataset_name')} data from GFW Analytics for {aoi_names}. {message_detail}.",
                    data_points_count=data_points_count,
                    analytics_api_url=analytics_url,
                )
            else:
                error_msg = f"Failed to pull {dataset.get('dataset_name')} data from GFW Analytics for {aoi_names} - URL: {endpoint_url}, payload: {payload}, response: {response.text}"
                logger.error(error_msg)
                return DataPullResult(
                    success=False,
                    data=None,
                    message=error_msg,
                    analytics_api_url=result.get("data", {}).get("link", None),
                    data_points_count=0,
                )

        except Exception as e:
            error_msg = f"Failed to pull {dataset.get('dataset_name')} data from Analytics API: {e}"
            logger.error(error_msg, exc_info=True)
            return DataPullResult(
                success=False,
                data=None,
                message=error_msg,
                analytics_api_url=None,
            )
