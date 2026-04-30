from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
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

    user = relationship("UserOrm", back_populates="machine_user_keys")


class InsightOrm(Base):
    __tablename__ = "insights"

    id = Column(
        PostgresUUID,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    thread_id = Column(String, nullable=False)
    insight_text = Column(String, nullable=False)
    follow_up_suggestions = Column(JSONB, nullable=False, server_default="[]")
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
