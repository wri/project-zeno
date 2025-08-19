from datetime import datetime
from typing import List, Optional
from uuid import UUID

from geojson_pydantic import Polygon
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    alias_generators,
    field_validator,
)

from src.api.data_models import UserType
from src.user_profile_configs.countries import COUNTRIES
from src.user_profile_configs.gis_expertise import GIS_EXPERTISE_LEVELS
from src.user_profile_configs.languages import LANGUAGES
from src.user_profile_configs.sectors import SECTOR_ROLES, SECTORS


class ThreadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    agent_id: str
    name: str
    is_public: bool
    created_at: datetime
    updated_at: datetime


class CustomAreaNameRequest(BaseModel):
    type: str = Field(
        "FeatureCollection", description="Type must be FeatureCollection"
    )
    features: list = Field(..., description="Array of GeoJSON Feature objects")


class UserModel(BaseModel):
    """User model with relationships to threads and custom areas."""

    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        from_attributes=True,
        populate_by_name=True,
    )
    id: str
    name: str
    email: str
    created_at: datetime
    updated_at: datetime
    threads: list[ThreadModel] = []
    user_type: UserType = UserType.REGULAR

    # New profile fields - Basic
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_description: Optional[str] = Field(
        None, description="What are you looking for or trying to do with Zeno?"
    )

    # New profile fields - Detailed
    sector_code: Optional[str] = None
    role_code: Optional[str] = None
    job_title: Optional[str] = None
    company_organization: Optional[str] = None
    country_code: Optional[str] = None
    preferred_language_code: Optional[str] = None
    gis_expertise_level: Optional[str] = None
    areas_of_interest: Optional[str] = None

    @field_validator("created_at", "updated_at", mode="before")
    def parse_dates(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).replace(tzinfo=None)
            except ValueError:
                return value
        return value

    @field_validator("sector_code")
    def validate_sector_code(cls, v):
        if v is not None and v not in SECTORS:
            raise ValueError(f"Invalid sector code: {v}")
        return v

    @field_validator("role_code")
    def validate_role_code(cls, v, info):
        if v is not None:
            sector_code = info.data.get("sector_code")
            if sector_code and sector_code in SECTOR_ROLES:
                if v not in SECTOR_ROLES[sector_code]:
                    raise ValueError(
                        f"Invalid role code: {v} for sector: {sector_code}"
                    )
            elif v != "other":
                raise ValueError(f"Invalid role code: {v}")
        return v

    @field_validator("country_code")
    def validate_country_code(cls, v):
        if v is not None and v not in COUNTRIES:
            raise ValueError(f"Invalid country code: {v}")
        return v

    @field_validator("preferred_language_code")
    def validate_language_code(cls, v):
        if v is not None and v not in LANGUAGES:
            raise ValueError(f"Invalid language code: {v}")
        return v

    @field_validator("gis_expertise_level")
    def validate_gis_expertise(cls, v):
        if v is not None and v not in GIS_EXPERTISE_LEVELS:
            raise ValueError(f"Invalid GIS expertise level: {v}")
        return v


class UserProfileUpdateRequest(BaseModel):
    """Request schema for updating user profile fields."""

    # Basic profile fields
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_description: Optional[str] = Field(
        None, description="What are you looking for or trying to do with Zeno?"
    )

    # Detailed profile fields
    sector_code: Optional[str] = None
    role_code: Optional[str] = None
    job_title: Optional[str] = None
    company_organization: Optional[str] = None
    country_code: Optional[str] = None
    preferred_language_code: Optional[str] = None
    gis_expertise_level: Optional[str] = None
    areas_of_interest: Optional[str] = None

    @field_validator("sector_code")
    def validate_sector_code(cls, v):
        if v is not None and v not in SECTORS:
            raise ValueError(f"Invalid sector code: {v}")
        return v

    @field_validator("role_code")
    def validate_role_code(cls, v, info):
        if v is not None:
            sector_code = info.data.get("sector_code")
            if sector_code and sector_code in SECTOR_ROLES:
                if v not in SECTOR_ROLES[sector_code]:
                    raise ValueError(
                        f"Invalid role code: {v} for sector: {sector_code}"
                    )
            elif v != "other":
                raise ValueError(f"Invalid role code: {v}")
        return v

    @field_validator("country_code")
    def validate_country_code(cls, v):
        if v is not None and v not in COUNTRIES:
            raise ValueError(f"Invalid country code: {v}")
        return v

    @field_validator("preferred_language_code")
    def validate_language_code(cls, v):
        if v is not None and v not in LANGUAGES:
            raise ValueError(f"Invalid language code: {v}")
        return v

    @field_validator("gis_expertise_level")
    def validate_gis_expertise(cls, v):
        if v is not None and v not in GIS_EXPERTISE_LEVELS:
            raise ValueError(f"Invalid GIS expertise level: {v}")
        return v


class ProfileConfigResponse(BaseModel):
    """Response schema for profile configuration options."""

    sectors: dict[str, str] = SECTORS
    sector_roles: dict[str, dict[str, str]] = SECTOR_ROLES
    countries: dict[str, str] = COUNTRIES
    languages: dict[str, str] = LANGUAGES
    gis_expertise_levels: dict[str, str] = GIS_EXPERTISE_LEVELS


class QuotaModel(BaseModel):
    """Quota information"""

    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        from_attributes=True,
        populate_by_name=True,
    )
    prompts_used: Optional[int] = Field(
        None, description="Number of prompts used today"
    )
    prompt_quota: Optional[int] = Field(
        None, description="Prompt quota for the user"
    )


class UserWithQuotaModel(UserModel, QuotaModel):
    """User model with quota information."""

    # model_config = ConfigDict(
    #     alias_generator=alias_generators.to_camel,
    #     from_attributes=True,
    #     populate_by_name=True,
    # )
    # prompts_used: Optional[int] = Field(
    #     None, description="Number of prompts used today"
    # )
    # prompt_quota: Optional[int] = Field(None, description="Prompt quota for the user")


class GeometryResponse(BaseModel):
    name: str = Field(..., description="Name of the geometry")
    subtype: str = Field(..., description="Subtype of the geometry")
    source: str = Field(..., description="Source of the geometry")
    src_id: int | str = Field(..., description="Source ID of the geometry")
    geometry: dict = Field(..., description="GeoJSON geometry")


class DailyUsageModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    date: datetime
    usage_count: int

    @field_validator("date", mode="before")
    def parse_date(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return value
        return value


class CustomAreaModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: str
    name: str
    geometries: List
    created_at: datetime
    updated_at: datetime


class CustomAreaCreate(BaseModel):
    name: str
    geometries: List[Polygon]


class ChatRequest(BaseModel):
    query: str = Field(..., description="The query")
    user_persona: Optional[str] = Field(None, description="The user persona")

    # UI Context - can include multiple selections
    ui_context: Optional[dict] = (
        None  # {"aoi_selected": {...}, "dataset_selected": {...}, "daterange_selected": {...}}
    )

    # Pure UI actions - no query
    ui_action_only: Optional[bool] = False

    # Chat info
    thread_id: Optional[str] = Field(None, description="The thread ID")
    metadata: Optional[dict] = Field(None, description="The metadata")
    session_id: Optional[str] = Field(None, description="The session ID")
    user_id: Optional[str] = Field(None, description="The user ID")
    tags: Optional[list] = Field(None, description="The tags")


class RatingCreateRequest(BaseModel):
    trace_id: str
    rating: int
    comment: Optional[str] = None

    @field_validator("rating")
    def validate_rating(cls, v):
        if v not in [-1, 1]:
            raise ValueError(
                "Rating must be either 1 (thumbs up) or -1 (thumbs down)"
            )
        return v


class RatingModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    thread_id: str
    trace_id: str
    rating: int
    comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime
