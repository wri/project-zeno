from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, alias_generators, field_validator
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class UserOrm(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now())
    updated_at = Column(DateTime, nullable=False, default=datetime.now())
    threads = relationship("ThreadOrm", back_populates="user")
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
        UniqueConstraint("user_id", "thread_id", "trace_id", name="uq_user_thread_trace_rating"),
    )

    id = Column(String, primary_key=True, unique=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    thread_id = Column(String, ForeignKey("threads.id"), nullable=False)
    trace_id = Column(String, nullable=False)
    rating = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now(),
        onupdate=datetime.now(),
    )
    user = relationship("UserOrm", back_populates="ratings", foreign_keys=[user_id])
    thread = relationship("ThreadOrm", back_populates="ratings", foreign_keys=[thread_id])


class ThreadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    agent_id: str
    name: str
    created_at: datetime
    updated_at: datetime


class UserModel(BaseModel):
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

    @field_validator("created_at", "updated_at", mode="before")
    def parse_dates(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return value
        return value


class RatingCreateRequest(BaseModel):
    thread_id: str
    trace_id: str
    rating: int

    @field_validator("rating")
    def validate_rating(cls, v):
        if v not in [-1, 1]:
            raise ValueError("Rating must be either 1 (thumbs up) or -1 (thumbs down)")
        return v


class RatingModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    thread_id: str
    trace_id: str
    rating: int
    created_at: datetime
    updated_at: datetime
