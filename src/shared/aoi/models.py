"""AOI domain models — single source of truth for AOI data structures."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AOISourceType(str, Enum):
    """The source table an AOI comes from."""

    GADM = "gadm"
    KBA = "kba"
    WDPA = "wdpa"
    LANDMARK = "landmark"
    CUSTOM = "custom"


class AOISubtype(str, Enum):
    """Administrative or area subtype."""

    COUNTRY = "country"
    STATE_PROVINCE = "state-province"
    DISTRICT_COUNTY = "district-county"
    MUNICIPALITY = "municipality"
    LOCALITY = "locality"
    NEIGHBOURHOOD = "neighbourhood"
    KEY_BIODIVERSITY_AREA = "key-biodiversity-area"
    PROTECTED_AREA = "protected-area"
    INDIGENOUS_LAND = "indigenous-and-community-land"
    CUSTOM_AREA = "custom-area"

    @property
    def is_admin(self) -> bool:
        return self in {
            AOISubtype.COUNTRY,
            AOISubtype.STATE_PROVINCE,
            AOISubtype.DISTRICT_COUNTY,
            AOISubtype.MUNICIPALITY,
            AOISubtype.LOCALITY,
            AOISubtype.NEIGHBOURHOOD,
        }


ADMIN_SUBTYPES_SET = frozenset(
    s for s in AOISubtype if s.is_admin
)


class AOI(BaseModel):
    """A single area of interest."""

    source: str = Field(description="Source table: gadm, kba, wdpa, landmark, custom")
    src_id: str = Field(description="Source-specific ID")
    name: str = Field(description="Display name")
    subtype: str = Field(description="Area subtype")

    @property
    def normalized_id(self) -> str:
        """ID suitable for analytics API — strips GADM _N suffix."""
        idx = str(self.src_id)
        if len(idx) > 2 and idx[-2:] in ("_1", "_2", "_3", "_4", "_5"):
            return idx[:-2]
        return idx

    @property
    def source_type(self) -> AOISourceType:
        return AOISourceType(self.source)

    def to_dict(self) -> dict:
        """Convert to dict matching the legacy format used throughout the codebase."""
        return {
            "source": self.source,
            "src_id": self.src_id,
            "name": self.name,
            "subtype": self.subtype,
        }


class AOISelection(BaseModel):
    """A named collection of AOIs — replaces the TypedDict in state.py."""

    name: str
    aois: list[AOI]
