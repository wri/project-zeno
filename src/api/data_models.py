from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
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

Base = declarative_base()


class UserType(str, enum.Enum):
    ADMIN = "admin"
    REGULAR = "regular"


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

    threads = relationship("ThreadOrm", back_populates="user")
    custom_areas = relationship("CustomAreaOrm", back_populates="user")
    ratings = relationship("RatingOrm", back_populates="user")


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
