"""Unified AOI domain model and source registry."""

from src.shared.aoi.models import AOI, AOISelection, AOISourceType, AOISubtype
from src.shared.aoi.registry import (
    AOISourceConfig,
    AnalyticsAPIMapping,
    all_sources,
    get_source,
    register_source,
)

__all__ = [
    "AOI",
    "AOISelection",
    "AOISourceType",
    "AOISubtype",
    "AOISourceConfig",
    "AnalyticsAPIMapping",
    "all_sources",
    "get_source",
    "register_source",
]
