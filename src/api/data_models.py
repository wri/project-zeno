from __future__ import annotations

from datetime import datetime, date
import enum

from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    String,
    Integer,
    text,
    UniqueConstraint,
)


from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class UserType(str, enum.Enum):
    ADMIN = "admin"
    REGULAR = "regular"


class UserOrm(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now())
    updated_at = Column(DateTime, nullable=False, default=datetime.now())
    user_type = Column(String, nullable=False, default=UserType.REGULAR.value)
    threads = relationship("ThreadOrm", back_populates="user")
    custom_areas = relationship("CustomAreaOrm", back_populates="user")
    ratings = relationship("RatingOrm", back_populates="user")


class ThreadOrm(Base):
    __tablename__ = "threads"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    agent_id = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now(),
        onupdate=datetime.now(),
    )
    name = Column(String, nullable=False, default="Unnamed Thread")
    user = relationship("UserOrm", back_populates="threads", foreign_keys=[user_id])
    ratings = relationship("RatingOrm", back_populates="thread")


class RatingOrm(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "thread_id", "trace_id", name="uq_user_thread_trace_rating"
        ),
    )

    id = Column(String, primary_key=True, unique=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    thread_id = Column(String, ForeignKey("threads.id"), nullable=False)
    trace_id = Column(String, nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now(),
        onupdate=datetime.now(),
    )
    user = relationship("UserOrm", back_populates="ratings", foreign_keys=[user_id])
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
        PostgresUUID, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    geometries = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now(),
        onupdate=datetime.now(),
    )

    user = relationship("UserOrm", back_populates="custom_areas")
