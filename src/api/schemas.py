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

    @field_validator("created_at", "updated_at", mode="before")
    def parse_dates(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).replace(tzinfo=None)
            except ValueError:
                return value
        return value


class UserWithQuotaModel(UserModel):
    """User model with quota information."""

    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        from_attributes=True,
        populate_by_name=True,
    )
    prompts_used: Optional[int] = Field(
        ..., description="Number of prompts used today"
    )
    prompt_quota: Optional[int] = Field(
        ..., description="Prompt quota for the user"
    )


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
