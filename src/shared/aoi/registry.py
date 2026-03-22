"""AOI source registry — each source self-describes its config."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from src.shared.aoi.models import AOISourceType, AOISubtype


@dataclass(frozen=True)
class AnalyticsAPIMapping:
    """How this source maps to the GFW analytics API aoi_type payload."""

    type: str
    provider: Optional[str] = None
    version: Optional[str] = None

    def to_payload(self) -> dict:
        d: dict = {"type": self.type}
        if self.provider:
            d["provider"] = self.provider
        if self.version:
            d["version"] = self.version
        return d


@dataclass(frozen=True)
class AOISourceConfig:
    """Everything needed to work with one AOI source."""

    source_type: AOISourceType
    table: str
    id_column: str
    subregion_limit: int
    analytics_mapping: AnalyticsAPIMapping
    coerce_id: Callable[[str], object] = field(default=str)
    valid_subtypes: frozenset[AOISubtype] = field(default_factory=frozenset)
    geometry_is_postgis: bool = True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[AOISourceType, AOISourceConfig] = {}


def register_source(config: AOISourceConfig) -> None:
    _REGISTRY[config.source_type] = config


def get_source(source: AOISourceType | str) -> AOISourceConfig:
    """Look up config by enum or string value."""
    if isinstance(source, str):
        source = AOISourceType(source)
    return _REGISTRY[source]


def all_sources() -> list[AOISourceConfig]:
    return list(_REGISTRY.values())


# ---------------------------------------------------------------------------
# Built-in registrations
# ---------------------------------------------------------------------------

register_source(
    AOISourceConfig(
        source_type=AOISourceType.GADM,
        table="geometries_gadm",
        id_column="gadm_id",
        subregion_limit=50,
        analytics_mapping=AnalyticsAPIMapping(
            type="admin", provider="gadm", version="4.1"
        ),
        valid_subtypes=frozenset(
            {
                AOISubtype.COUNTRY,
                AOISubtype.STATE_PROVINCE,
                AOISubtype.DISTRICT_COUNTY,
                AOISubtype.MUNICIPALITY,
                AOISubtype.LOCALITY,
                AOISubtype.NEIGHBOURHOOD,
            }
        ),
    )
)

register_source(
    AOISourceConfig(
        source_type=AOISourceType.KBA,
        table="geometries_kba",
        id_column="sitrecid",
        subregion_limit=25,
        analytics_mapping=AnalyticsAPIMapping(type="key_biodiversity_area"),
        coerce_id=lambda x: int(x),
        valid_subtypes=frozenset({AOISubtype.KEY_BIODIVERSITY_AREA}),
    )
)

register_source(
    AOISourceConfig(
        source_type=AOISourceType.WDPA,
        table="geometries_wdpa",
        id_column="wdpa_pid",
        subregion_limit=25,
        analytics_mapping=AnalyticsAPIMapping(type="protected_area"),
        valid_subtypes=frozenset({AOISubtype.PROTECTED_AREA}),
    )
)

register_source(
    AOISourceConfig(
        source_type=AOISourceType.LANDMARK,
        table="geometries_landmark",
        id_column="landmark_id",
        subregion_limit=25,
        analytics_mapping=AnalyticsAPIMapping(type="indigenous_land"),
        valid_subtypes=frozenset({AOISubtype.INDIGENOUS_LAND}),
    )
)

register_source(
    AOISourceConfig(
        source_type=AOISourceType.CUSTOM,
        table="custom_areas",
        id_column="id",
        subregion_limit=25,
        analytics_mapping=AnalyticsAPIMapping(type="feature_collection"),
        valid_subtypes=frozenset({AOISubtype.CUSTOM_AREA}),
        geometry_is_postgis=False,
    )
)
