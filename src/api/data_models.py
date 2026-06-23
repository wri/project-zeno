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
    Float,
    ForeignKey,
    Index,
    Integer,
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
    start_date = Column(String, nullable=False)
    end_date = Column(String, nullable=False)
    source_url = Column(String, nullable=True)
    aoi_names = Column(JSONB, nullable=False, server_default="[]")
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
    is_final_turn_in_thread = Column(Boolean, nullable=True)

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
