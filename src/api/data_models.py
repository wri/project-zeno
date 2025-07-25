from __future__ import annotations

from datetime import datetime, date
import enum
from uuid import UUID
from typing import List

from pydantic import BaseModel, ConfigDict, alias_generators, field_validator, Field
from geojson_pydantic import Polygon
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Integer, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

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


class ThreadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    agent_id: str
    name: str
    created_at: datetime
    updated_at: datetime


class CustomAreaNameRequest(BaseModel):
    type: str = Field("FeatureCollection", description="Type must be FeatureCollection")
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
                return datetime.fromisoformat(value)
            except ValueError:
                return value
        return value


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
