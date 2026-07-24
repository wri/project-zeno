"""API metadata endpoint."""

from fastapi import APIRouter

from src.agent.config import AgentSettings
from src.agent.datasets.palette import PALETTES
from src.agent.llms import get_model, get_small_model
from src.api.schemas import DatasetCatalogResponse
from src.shared.geocoding_helpers import (
    GADM_SUBTYPE_MAP,
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
)
from src.shared.version import get_version

router = APIRouter()


@router.get("/api/metadata")
async def api_metadata() -> dict:
    """
    Returns API metadata helpful for instantiating the frontend.

    Includes layer ID mappings, subregion/subtype mappings, and model
    information.
    """
    current_model = get_model()
    current_model_name = AgentSettings.model.lower()
    small_model = get_small_model()
    small_model_name = AgentSettings.small_model.lower()

    return {
        "version": get_version(),
        "layer_id_mapping": {
            key: value["id_column"] for key, value in SOURCE_ID_MAPPING.items()
        },
        "subregion_to_subtype_mapping": SUBREGION_TO_SUBTYPE_MAPPING,
        "gadm_subtype_mapping": GADM_SUBTYPE_MAP,
        "model": {
            "current": current_model_name,
            "model_class": current_model.__class__.__name__,
            "small": small_model_name,
            "small_model_class": small_model.__class__.__name__,
        },
    }


@router.get("/api/datasets/catalog")
async def datasets_catalog() -> DatasetCatalogResponse:
    """
    Returns the canonical color registry for each dataset: category colors
    (keyed by a stable English slug, not a translated label), single-series
    colors, and divergent (positive/negative) colors.

    This is the single source of truth for chart and map-legend colors —
    see docs/insight-chart-colors-plan.md. Only datasets with color data
    defined in their catalog YAML are included.
    """
    ordered = sorted(PALETTES.values(), key=lambda p: p["dataset_id"])
    return DatasetCatalogResponse.model_validate({"datasets": ordered})
