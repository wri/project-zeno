from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from geojson_pydantic import Polygon
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    alias_generators,
    field_validator,
    model_validator,
)

from src.api.data_models import UserType
from src.api.user_profile_configs.countries import COUNTRIES
from src.api.user_profile_configs.gis_expertise import GIS_EXPERTISE_LEVELS
from src.api.user_profile_configs.languages import LANGUAGES
from src.api.user_profile_configs.sectors import SECTOR_ROLES, SECTORS
from src.api.user_profile_configs.topics import TOPICS


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


class CustomAreaNameResponse(BaseModel):
    name: str = Field(
        ...,
        description="Generated geographic name for the area",
        max_length=100,
    )

    @field_validator("name", mode="before")
    def truncate_area_name(cls, value):
        if isinstance(value, str) and len(value) > 100:
            return value[:100]
        return value


class ThreadNameOutput(BaseModel):
    name: str = Field(
        ...,
        description="Generated name for thread",
        max_length=50,
    )

    @field_validator("name", mode="before")
    def truncate_thread_name(cls, value):
        if isinstance(value, str) and len(value) > 50:
            return value[:50]
        return value


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
    topics: Optional[List[str]] = None
    receive_news_emails: bool = False
    help_test_features: bool = False
    has_profile: bool = False

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

    @field_validator("topics")
    def validate_topics(cls, v):
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("Topics must be a list")
            for topic in v:
                if topic not in TOPICS:
                    raise ValueError(f"Invalid topic: {topic}")
        return v


class UserTypeUpdateRequest(BaseModel):
    """Request schema for changing a user's user_type via the admin endpoint."""

    user_type: UserType

    @field_validator("user_type")
    def reject_machine(cls, v: UserType) -> UserType:
        if v == UserType.MACHINE:
            raise ValueError(
                "machine user_type cannot be assigned via this endpoint"
            )
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
    topics: Optional[List[str]] = None
    receive_news_emails: Optional[bool] = None
    help_test_features: Optional[bool] = None
    has_profile: Optional[bool] = None

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

    @field_validator("topics")
    def validate_topics(cls, v):
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("Topics must be a list")
            for topic in v:
                if topic not in TOPICS:
                    raise ValueError(f"Invalid topic: {topic}")
        return v


class ProfileConfigResponse(BaseModel):
    """Response schema for profile configuration options."""

    sectors: dict[str, str] = SECTORS
    sector_roles: dict[str, dict[str, str]] = SECTOR_ROLES
    countries: dict[str, str] = COUNTRIES
    languages: dict[str, str] = LANGUAGES
    gis_expertise_levels: dict[str, str] = GIS_EXPERTISE_LEVELS
    topics: dict[str, str] = TOPICS


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


class AOISearchResult(BaseModel):
    """A single AOI returned by the ``GET /api/aois`` search endpoint."""

    source: str = Field(
        ...,
        description="Source of the AOI (gadm, kba, wdpa, landmark, custom)",
    )
    src_id: str = Field(..., description="Source-specific ID of the AOI")
    name: str = Field(..., description="Name of the AOI")
    subtype: str = Field(..., description="Subtype of the AOI")
    bbox: List[float] = Field(
        default=[-180.0, -90.0, 180.0, 90.0],
        description="Bounding box as [minx, miny, maxx, maxy]",
    )


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

    # Ambient frontend view state — what the user is currently looking at.
    # Unlike ui_context (deliberate actions), this is reference material the
    # agent consults on demand via the inspect_view_context tool; it is NOT
    # turned into a message or eagerly merged into the agent's selections.
    # Free-form (the frontend owns the shape), e.g.:
    #   {"page": "map" | "report",
    #    "viewport": {"bbox": [minx, miny, maxx, maxy], "zoom": 5},
    #    "visible_layers": [{"id": "...", "name": "..."}],
    #    "visible_aois": [{"source": "...", "src_id": "...", "name": "..."}],
    #    "visible_insights": ["<uuid>", "<uuid>"]}
    # On the dashboard page the snapshot carries the dashboard being viewed:
    #   {"page": "dashboard", "dashboard_id": "<uuid>", "dashboard_name": "…"}
    # Known "page" values get scope semantics on the backend (session-block
    # line + system-prompt section) via src/agent/view_pages.py; see
    # docs/view-context-pages.md. Unknown pages degrade gracefully.
    view_context: Optional[dict] = Field(
        None,
        description="Ambient frontend view state (page, viewport, visible layers/AOIs)",
    )

    # Pure UI actions - no query
    ui_action_only: Optional[bool] = False

    # Feature flag: selects the agent tool profile for this request.
    ff: Optional[str] = Field(
        None,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description="Feature flag selecting the agent profile (slug: lowercase, digits, hyphens)",
    )

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


class ThreadUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="The name of the thread")
    is_public: Optional[bool] = Field(
        None,
        description="Whether the thread is publicly accessible. True = anyone can view without auth, False = owner only",
    )


class ThreadStateResponse(BaseModel):
    """Response model for thread state endpoint."""

    thread_id: str
    state: str = Field(
        ..., description="JSON serialized agent state for the thread"
    )


class CodeActPartResponse(BaseModel):
    type: str
    content: str


class InsightChartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    title: str
    chart_type: str
    x_axis: str
    y_axis: str
    color_field: str
    stack_field: str
    group_field: str
    series_fields: List[str]
    chart_data: List[dict]


class InsightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[str] = None
    thread_id: Optional[str] = None
    insight_text: str
    follow_up_suggestions: List[str]
    statistics_ids: List[str] = []
    charts: List[InsightChartResponse]
    codeact_parts: List[CodeActPartResponse]
    is_public: bool
    created_at: datetime


class InsightPublicToggleRequest(BaseModel):
    is_public: bool


class JobResourceResponse(BaseModel):
    id: UUID
    resource_url: str = Field(
        description="URL of the created resource, e.g. `/api/insights/{id}`."
    )
    status: str = Field(description="Always `completed`.")
    created_at: datetime


class JobResponse(BaseModel):
    id: UUID
    type: str = Field(description="Job type, e.g. `analysis`.")
    status: str = Field(
        description=(
            "Current job status: `pending`, `running`, `completed`, or "
            "`failed`. While `pending` or `running`, poll again after the "
            "number of seconds in the `Retry-After` response header."
        )
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="Agent thread the results were written into, if provided.",
    )
    resources: List[JobResourceResponse] = Field(
        default=[],
        description=(
            "Resources created by the job. Empty until the job completes. "
            "Follow each `resource_url` to retrieve the result."
        ),
    )
    created_at: datetime


class AreaOfInterest(BaseModel):
    source: str = Field(
        description=(
            "Data source of the area, e.g. `gadm`, `custom`, `wdpa`, "
            "`kba`, `landmark`."
        )
    )
    src_id: str = Field(
        description="Source-specific identifier, e.g. `BRA` or a UUID."
    )
    subtype: str = Field(
        description=(
            "Administrative level or area category, e.g. `country`, "
            "`state-province`, `custom-area`."
        )
    )


class AnalyzeRequest(BaseModel):
    aois: List[AreaOfInterest] = Field(
        min_length=1,
        description="One or more areas of interest to analyse.",
    )
    dataset_id: int = Field(description="ID of the dataset to query.")
    start_date: date = Field(
        description="Start of the date range (YYYY-MM-DD)."
    )
    end_date: date = Field(description="End of the date range (YYYY-MM-DD).")
    thread_id: Optional[str] = Field(
        default=None,
        description=(
            "Agent thread ID. When provided, the results are written into "
            "the agent state for that thread so follow-up chat messages can "
            "reference the data without re-fetching."
        ),
    )


class DashboardAoi(AreaOfInterest):
    """An AOI reference on a dashboard: canonical address plus display name."""

    name: str = Field(description="Display name of the area, e.g. `Paraná`.")


class DashboardCreateRequest(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description="Dashboard name; defaults to the first AOI's name.",
    )
    description: Optional[str] = None
    # min/max length 1 is the MVP single-area constraint — the schema supports
    # multiple areas (portfolios); lift later by raising max_length.
    aois: List[DashboardAoi] = Field(min_length=1, max_length=1)


class DashboardUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class DashboardPublicToggleRequest(BaseModel):
    is_public: bool


_WIDGET_TYPES = ("insight", "map")


class DashboardWidgetCreateRequest(BaseModel):
    widget_type: str = Field(
        description="Widget kind: `insight` or `map`.",
    )
    insight_id: Optional[UUID] = Field(
        default=None,
        description="Insight the widget references; required for `insight` widgets.",
    )
    config: Optional[dict] = Field(
        default=None,
        description=(
            "Widget config. Insight widgets: presentation only — "
            "`default_view` (map|chart|table), optional `title` override. "
            "Map widgets: a self-contained layer snapshot under exactly one "
            "of the keys `dataset` (resolved tile_url, context layers, "
            "parameters, dates) or `imagery` (Sentinel-2 mosaic_id and tile "
            "URLs); optional `viewport` override — by default map widgets "
            "render fitted to the dashboard's area."
        ),
    )
    position: Optional[int] = None

    @field_validator("widget_type")
    def validate_widget_type(cls, v):
        if v not in _WIDGET_TYPES:
            raise ValueError(
                f"widget_type must be one of {', '.join(_WIDGET_TYPES)}"
            )
        return v

    @model_validator(mode="after")
    def validate_map_config(self) -> "DashboardWidgetCreateRequest":
        """Map widgets need a renderable layer snapshot in config.

        Only the discriminator and its tile_url are checked — the remaining
        snapshot keys may evolve without a schema change here.
        """
        if self.widget_type != "map":
            return self
        config = self.config or {}
        kinds = [k for k in ("dataset", "imagery") if k in config]
        if len(kinds) != 1:
            raise ValueError(
                "map widgets require a config with exactly one of "
                "'dataset' or 'imagery'"
            )
        layer = config[kinds[0]]
        if not isinstance(layer, dict) or not layer.get("tile_url"):
            raise ValueError(
                f"map widget {kinds[0]} config requires a tile_url"
            )
        return self


class DashboardWidgetUpdateRequest(BaseModel):
    position: Optional[int] = None
    config: Optional[dict] = None


class DashboardAoiResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    src_id: str
    subtype: str
    name: str
    position: int


class DashboardWidgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    widget_type: str
    insight_id: Optional[UUID] = None
    config: dict
    created_at: datetime
    # Expanded insight payload (same shape the insights endpoints return) so
    # the frontend renders widgets like insights. Populated on the single-
    # dashboard endpoint; None when the insight is not visible to the viewer.
    insight: Optional[InsightResponse] = None


class DashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: str
    name: str
    description: Optional[str] = None
    is_public: bool
    created_at: datetime
    updated_at: datetime
    aois: List[DashboardAoiResponse] = []
    widgets: List[DashboardWidgetResponse] = []


class DashboardPublicToggleResponse(DashboardResponse):
    publicized_insight_ids: List[UUID] = Field(
        default=[],
        description=(
            "Insights flipped to public because this dashboard was published."
        ),
    )
