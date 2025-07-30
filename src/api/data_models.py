from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, alias_generators, field_validator, Field
from sqlalchemy import Column, DateTime, ForeignKey, String
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


class GeometryResponse(BaseModel):
    name: str = Field(..., description="Name of the geometry")
    subtype: str = Field(..., description="Subtype of the geometry")
    source: str = Field(..., description="Source of the geometry")
    src_id: int | str = Field(..., description="Source ID of the geometry")
    geometry: dict = Field(..., description="GeoJSON geometry")
