from __future__ import annotations

from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geometry
from geojson_pydantic import Polygon
from pydantic import BaseModel, ConfigDict, alias_generators, field_validator
from sqlalchemy import Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class UserOrm(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now())
    updated_at = Column(DateTime, nullable=False, default=datetime.now())
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


class CustomAreaOrm(Base):
    __tablename__ = "custom_areas"

    id = Column(PostgresUUID, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    geometry = Column(Geometry(geometry_type='GEOMETRY', srid=4326), nullable=False)
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

    @field_validator("created_at", "updated_at", mode="before")
    def parse_dates(cls, value):
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
    geometry: Polygon
    created_at: datetime
    updated_at: datetime


class CustomAreaCreate(BaseModel):
    name: str
    geometry: Polygon
