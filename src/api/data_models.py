from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import declarative_base, relationship

# Add Any declaration so mypy knows Base is a class.
Base: Any = declarative_base()


class UserType(str, enum.Enum):
    ADMIN = "admin"
    REGULAR = "regular"
    MACHINE = "machine"
    PRO = "pro"
    SUPERUSER = "superuser"


class UserOrm(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    user_type = Column(String, nullable=False, default=UserType.REGULAR.value)

    # New profile fields - Basic
    first_name = Column(String, nullable=True)
    last_name = Column(
        String, nullable=True
    )  # Made nullable since existing users won't have this
    profile_description = Column(String, nullable=True)

    # New profile fields - Detailed
    sector_code = Column(String, nullable=True)
    role_code = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    company_organization = Column(String, nullable=True)
    country_code = Column(String, nullable=True)
    preferred_language_code = Column(String, nullable=True)
    gis_expertise_level = Column(String, nullable=True)
    areas_of_interest = Column(String, nullable=True)
    topics = Column(
        String, nullable=True
    )  # JSON array of selected topic codes
    receive_news_emails = Column(Boolean, nullable=False, default=False)
    help_test_features = Column(Boolean, nullable=False, default=False)
    has_profile = Column(Boolean, nullable=False, default=False)

    # Machine user fields
    machine_description = Column(String, nullable=True)

    threads = relationship("ThreadOrm", back_populates="user")
    custom_areas = relationship("CustomAreaOrm", back_populates="user")
    ratings = relationship("RatingOrm", back_populates="user")
    machine_user_keys = relationship(
        "MachineUserKeyOrm", back_populates="user"
    )
    user_aois = relationship("UserAoiOrm", back_populates="user")


class ThreadOrm(Base):
    __tablename__ = "threads"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    agent_id = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
    )
    name = Column(String, nullable=False, default="Unnamed Thread")
    is_public = Column(Boolean, nullable=False, default=False)
    user = relationship(
        "UserOrm", back_populates="threads", foreign_keys=[user_id]
    )
    ratings = relationship("RatingOrm", back_populates="thread")


class RatingOrm(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "thread_id",
            "trace_id",
            name="uq_user_thread_trace_rating",
        ),
    )

    id = Column(String, primary_key=True, unique=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    thread_id = Column(String, ForeignKey("threads.id"), nullable=False)
    trace_id = Column(String, nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
    )
    user = relationship(
        "UserOrm", back_populates="ratings", foreign_keys=[user_id]
    )
    thread = relationship(
        "ThreadOrm", back_populates="ratings", foreign_keys=[thread_id]
    )


class DailyUsageOrm(Base):
    __tablename__ = "daily_usage"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    date = Column(Date, nullable=False, primary_key=True, default=date.today())
    usage_count = Column(Integer, nullable=False, default=0)
    ip_address = Column(String, nullable=True)


class CustomAreaOrm(Base):
    __tablename__ = "custom_areas"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    geometries = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
    )

    user = relationship("UserOrm", back_populates="custom_areas")


class AoiRelationship(str, enum.Enum):
    """A user's relationship to an AOI in ``user_aois``.

    ``owner`` may edit the AOI; ``saved`` is read-only. Having any row means the
    AOI is in the user's list. Shared/collaborator relationships will be added
    when those use-cases are built.
    """

    OWNER = "owner"
    SAVED = "saved"


class AoiOrm(Base):
    """Unified AOI table: one row per live ``(source, source_id)``.

    Holds every kind of area -- reference sources (gadm/kba/wdpa/landmark) and
    custom drawn areas -- addressed by a stable UUID ``id`` and by the logical
    ``(source, source_id)`` key.

    Deliberately PostGIS-free at the ORM layer, like the rest of this module:
    the real ``geometry geometry(GEOMETRY, 4326)`` column plus the GiST,
    partial trigram, and partial-unique indexes live in the Alembic migration
    only. The test DB is built from this metadata via ``create_all`` and has no
    PostGIS/pg_trgm; geometry is read/written through raw SQL (see
    ``src/shared/geocoding_helpers.py``).
    """

    __tablename__ = "aois"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    subtype = Column(String, nullable=False)
    # bbox as [west, south, east, north]; precomputed, antimeridian-aware.
    bbox = Column(ARRAY(Float), nullable=True)
    area_km2 = Column(Float, nullable=True)
    iso3 = Column(ARRAY(String), nullable=True)
    admin_level = Column(SmallInteger, nullable=True)
    # Kept in the table but excluded from search via a partial index.
    is_disputed = Column(Boolean, nullable=False, default=False)
    # Inert today; reserved for future versioning (deprecate-old on update).
    is_deprecated = Column(Boolean, nullable=False, default=False)
    # Provenance / "uploaded_by": set for custom areas, null for reference.
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    # Arbitrary/source-specific key-values: escape hatch for user-uploaded
    # custom-AOI attributes and source columns that don't map to the typed
    # columns above. Left NULL by build-aois for now; anything we
    # filter/facet/sort on gets promoted to a real column instead.
    properties = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
    )

    user_links = relationship(
        "UserAoiOrm",
        back_populates="aoi",
        cascade="all, delete-orphan",
    )


class UserAoiOrm(Base):
    """User<->AOI relationships: owner / saved.

    A single join carrying the whole permission model. ``aoi_id`` is a clean
    single-column FK to ``aois.id`` (the payoff of unifying storage). "In my
    list" == any row for the user; ``relationship`` says what they may do.
    """

    __tablename__ = "user_aois"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    aoi_id = Column(
        PostgresUUID,
        ForeignKey("aois.id", ondelete="CASCADE"),
        nullable=False,
    )
    # native_enum=False -> VARCHAR + CHECK, so create_all needs no PG type.
    relationship_type = Column(
        "relationship",
        Enum(
            AoiRelationship,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [m.value for m in e],
            name="aoi_relationship",
        ),
        nullable=False,
    )
    # User's per-list label; null falls back to aois.name.
    name = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "aoi_id",
            "relationship",
            name="uq_user_aoi_relationship",
        ),
        # Powers custom-visibility semi-join and saved-first sort.
        Index(
            "idx_user_aois_user_rel_aoi",
            "user_id",
            "relationship",
            "aoi_id",
        ),
        Index("idx_user_aois_aoi_id", "aoi_id"),
    )

    user = relationship("UserOrm", back_populates="user_aois")
    aoi = relationship("AoiOrm", back_populates="user_links")


class MachineUserKeyOrm(Base):
    __tablename__ = "machine_user_keys"

    id = Column(
        PostgresUUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    key_name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False)
    key_prefix = Column(String(8), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    scopes = Column(ARRAY(String), nullable=False, server_default="{}")

    user = relationship("UserOrm", back_populates="machine_user_keys")


class StatisticsOrm(Base):
    __tablename__ = "statistics"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    thread_id = Column(String, nullable=True)
    dataset_name = Column(String, nullable=False)
    # Catalog id of the dataset (parallel to dataset_name). Nullable so existing
    # rows stay valid without backfill.
    dataset_id = Column(Integer, nullable=True)
    start_date = Column(String, nullable=False)
    end_date = Column(String, nullable=False)
    source_url = Column(String, nullable=True)
    aoi_names = Column(JSONB, nullable=False, server_default="[]")
    # src_ids of the analysed AOIs, parallel to aoi_names. src_id is only unique
    # per source, so aoi_sources carries the matching source for each entry.
    aoi_ids = Column(JSONB, nullable=False, server_default="[]")
    aoi_sources = Column(JSONB, nullable=False, server_default="[]")
    parameters = Column(JSONB, nullable=True)
    context_layer = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class InsightOrm(Base):
    __tablename__ = "insights"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    thread_id = Column(String, nullable=True)
    insight_text = Column(String, nullable=False)
    follow_up_suggestions = Column(JSONB, nullable=False, server_default="[]")
    statistics_ids = Column(JSONB, nullable=False, server_default="[]")
    codeact_types = Column(ARRAY(String), nullable=False, server_default="{}")
    codeact_contents = Column(
        ARRAY(String), nullable=False, server_default="{}"
    )

    is_public = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    charts = relationship(
        "InsightChartOrm",
        back_populates="insight",
        cascade="all, delete-orphan",
        order_by="InsightChartOrm.position",
    )


class InsightChartOrm(Base):
    __tablename__ = "insight_charts"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    insight_id = Column(
        PostgresUUID, ForeignKey("insights.id"), nullable=False
    )
    position = Column(Integer, nullable=False, server_default="0")
    title = Column(String, nullable=False)
    chart_type = Column(String, nullable=False)
    x_axis = Column(String, nullable=False, server_default="")
    y_axis = Column(String, nullable=False, server_default="")
    color_field = Column(String, nullable=False, server_default="")
    stack_field = Column(String, nullable=False, server_default="")
    group_field = Column(String, nullable=False, server_default="")
    series_fields = Column(JSONB, nullable=False, server_default="[]")
    chart_data = Column(JSONB, nullable=False)

    insight = relationship("InsightOrm", back_populates="charts")


class DashboardOrm(Base):
    __tablename__ = "dashboards"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_public = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
    )

    aois = relationship(
        "DashboardAoiOrm",
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardAoiOrm.position",
    )
    widgets = relationship(
        "DashboardWidgetOrm",
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardWidgetOrm.position",
    )


class DashboardAoiOrm(Base):
    """An AOI reference on a dashboard — the canonical (source, src_id,
    subtype) address plus a denormalized display name, never geometry."""

    __tablename__ = "dashboard_aois"
    __table_args__ = (
        UniqueConstraint(
            "dashboard_id",
            "source",
            "src_id",
            name="uq_dashboard_aois_dashboard_source_src_id",
        ),
    )

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    dashboard_id = Column(
        PostgresUUID, ForeignKey("dashboards.id"), nullable=False
    )
    source = Column(String, nullable=False)
    src_id = Column(String, nullable=False)
    subtype = Column(String, nullable=False)
    name = Column(String, nullable=False)
    position = Column(Integer, nullable=False, server_default="0")

    dashboard = relationship("DashboardOrm", back_populates="aois")


class DashboardWidgetOrm(Base):
    """One widget on a dashboard. Insight widgets reference an insight and
    carry presentation config only. Map widgets are self-contained: their
    `config` snapshots the resolved layer (tile URLs included by design)
    under a `dataset` or `imagery` key — never chart data or geometry."""

    __tablename__ = "dashboard_widgets"

    # An insight appears on a dashboard at most once, enforced at the DB so
    # retries (agent after an ambiguous error, REST client after a dropped
    # response) cannot duplicate widgets. Map/text widgets are exempt.
    __table_args__ = (
        Index(
            "uq_dashboard_widgets_dashboard_insight",
            "dashboard_id",
            "insight_id",
            unique=True,
            postgresql_where=text("widget_type = 'insight'"),
        ),
    )

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    dashboard_id = Column(
        PostgresUUID, ForeignKey("dashboards.id"), nullable=False
    )
    position = Column(Integer, nullable=False, server_default="0")
    # "insight" | "map" — plain String like JobOrm.type; validated in Pydantic.
    widget_type = Column(String, nullable=False)
    # Deleting an insight silently drops widgets that reference it.
    insight_id = Column(
        PostgresUUID,
        ForeignKey("insights.id", ondelete="CASCADE"),
        nullable=True,
    )
    # default_view ("map"|"chart"|"table"), optional title override; for map
    # widgets a layer snapshot under exactly one of "dataset" (resolved
    # tile_url, context layers, parameters, dates) or "imagery" (Sentinel-2
    # mosaic_id + tile URLs), plus an optional viewport override.
    # A future `refresh` key (relative date window) is reserved, not implemented.
    config = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    dashboard = relationship("DashboardOrm", back_populates="widgets")


class JobOrm(Base):
    __tablename__ = "jobs"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    thread_id = Column(String, nullable=True)
    type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )

    resources = relationship(
        "JobResourceOrm",
        back_populates="job",
        order_by="JobResourceOrm.created_at",
    )


class JobResourceOrm(Base):
    __tablename__ = "job_resources"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    job_id = Column(PostgresUUID, ForeignKey("jobs.id"), nullable=False)
    resource_url = Column(String, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    job = relationship("JobOrm", back_populates="resources")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LangfuseTraceOrm(Base):
    """Derived analytics for one Langfuse trace (= one agent turn).

    Stores only the small derived/analytics columns — Langfuse remains the store
    of record for the full raw trace, fetched on demand for the detail view.
    Domain fields are parsed against the agent's own ``AgentState`` contract
    (src/agent/state.py); turn-level metrics are computed from the active-turn
    message window (NOT the whole accumulated history). ``session_id`` /
    ``user_id`` / ``insight_id`` are SOFT references (nullable, no FK) — many
    traces won't match (machine users, dev envs, deleted threads), so all joins
    are LEFT JOINs and resolve-rate is monitored.
    """

    __tablename__ = "langfuse_traces"

    # Langfuse trace id
    id = Column(String, primary_key=True, nullable=False)

    # Soft references (no FK by design)
    session_id = Column(String, nullable=True)  # == threads.id
    user_id = Column(String, nullable=True)  # == users.id
    environment = Column(String, nullable=True)

    # Timestamps from the trace (tz-aware UTC — deliberately not the naive
    # datetime.now convention used by older tables in this module).
    trace_timestamp = Column(DateTime(timezone=True), nullable=True)
    trace_updated_at = Column(DateTime(timezone=True), nullable=True)

    # --- Turn-level metrics (from the active-turn window) ---
    prompt = Column(String, nullable=True)
    answer = Column(String, nullable=True)
    turn_input_tokens = Column(Integer, nullable=True)
    turn_output_tokens = Column(Integer, nullable=True)
    turn_tokens = Column(Integer, nullable=True)
    turn_tool_calls = Column(Integer, nullable=True)
    # Passthrough per-turn fields from the trace top level.
    latency_seconds = Column(Float, nullable=True)
    total_cost = Column(Float, nullable=True)

    # Outcome primitives (durable, auditable signals). ``outcome`` is the label
    # derived FROM these — retuning the rule is a recompute, not a reparse.
    has_answer = Column(Boolean, nullable=True)
    answer_finish_reason = Column(String, nullable=True)
    answer_is_refusal = Column(Boolean, nullable=True)
    had_tool_call = Column(Boolean, nullable=True)
    tool_error_count = Column(Integer, nullable=True)
    outcome = Column(String, nullable=True)

    # --- Current-state columns (per-turn-meaningful, from output snapshot) ---
    aoi_name = Column(String, nullable=True)
    aoi_type = Column(String, nullable=True)
    primary_dataset_name = Column(String, nullable=True)
    has_insight = Column(Boolean, nullable=True)
    is_global = Column(Boolean, nullable=True)
    insight_id = Column(String, nullable=True)  # soft FK -> insights.id
    # Turn position within the session (1-based, ordered by trace_timestamp).
    # Stored (not a query-time window) so it is index-filterable; maintained by a
    # session-scoped recompute in the ingest path. Null-session traces are
    # singleton threads (turn_index 1, is_final True).
    turn_index = Column(Integer, nullable=True)
    is_final_turn_in_thread = Column(Boolean, nullable=True)

    # --- Per-turn diffs (honest "this turn" signals vs. the cumulative fields
    # above). Cross-row, so maintained by the same ingest recompute as turn_index
    # (null-session singletons are set directly in build_row).
    # insight_created_this_turn: insight_id changed to non-null on this turn.
    # datasets_analysed_this_turn: datasets new this turn (cumulative minus prior).
    insight_created_this_turn = Column(Boolean, nullable=True)
    datasets_analysed_this_turn = Column(ARRAY(String), nullable=True)

    # Long-tail + cumulative derived fields, kept out of the column set to keep
    # migrations rare. Includes turn_tools_used, turn_datasets, aoi_source,
    # aoi_count, aois, primary_dataset_id, analysis_start/end_date,
    # cache_read_tokens, language(+confidence), datasets_analysed_cumulative,
    # statistics_ids, state_snapshot, and unknown_output_keys (drift detector).
    derived = Column(JSONB, nullable=True)

    # Bookkeeping / drift detection
    parser_version = Column(Integer, nullable=False, default=1)
    ingested_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    parsed_at = Column(DateTime(timezone=True), nullable=True)
    parse_error = Column(String, nullable=True)
    recognized_contract = Column(Boolean, nullable=True)

    __table_args__ = (
        Index("ix_langfuse_traces_trace_timestamp", "trace_timestamp"),
        Index("ix_langfuse_traces_user_id", "user_id"),
        Index("ix_langfuse_traces_session_id", "session_id"),
        Index("ix_langfuse_traces_insight_id", "insight_id"),
        Index("ix_langfuse_traces_env_ts", "environment", "trace_timestamp"),
        Index("ix_langfuse_traces_turn_index", "turn_index"),
        # Serves "first turns, newest first" (first_turn_only) directly.
        Index(
            "ix_langfuse_traces_first_turn",
            text("trace_timestamp DESC"),
            postgresql_where=text("turn_index = 1"),
        ),
    )


class LangfuseIngestionRunOrm(Base):
    """One ingestion run (or backfill chunk): watermark bookkeeping + drift
    observability. ``fill_rates``/``fk_resolve_rates``/``unrecognized_contract_rate``
    are the primary defense against silent contract drift — alert on day-over-day
    deltas, not just on status=failed."""

    __tablename__ = "langfuse_ingestion_runs"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    started_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)
    window_start = Column(DateTime(timezone=True), nullable=True)
    window_end = Column(DateTime(timezone=True), nullable=True)
    environment = Column(String, nullable=True)  # null = all environments

    traces_fetched = Column(Integer, nullable=False, default=0)
    traces_upserted = Column(Integer, nullable=False, default=0)
    chunks_total = Column(Integer, nullable=True)
    chunks_failed = Column(Integer, nullable=True)

    parser_version = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="running")
    error = Column(String, nullable=True)
    # Max trace_timestamp successfully ingested as part of a contiguous window.
    watermark = Column(DateTime(timezone=True), nullable=True)

    # Drift observability
    fill_rates = Column(JSONB, nullable=True)
    fk_resolve_rates = Column(JSONB, nullable=True)
    unrecognized_contract_rate = Column(Float, nullable=True)
