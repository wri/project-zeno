from __future__ import annotations

from datetime import datetime, date
import enum
from pydantic import BaseModel, ConfigDict, alias_generators, field_validator
from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Integer
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
    user = relationship("UserOrm", back_populates="threads", foreign_keys=[user_id])


class DailyUsageOrm(Base):
    __tablename__ = "daily_usage"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    date = Column(Date, nullable=False, primary_key=True, default=date.today())
    usage_count = Column(Integer, nullable=False, default=0)


class ThreadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    agent_id: str
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
    user_type: UserType = UserType.REGULAR

    @field_validator("created_at", "updated_at", mode="before")
    def parse_dates(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return value
        return value


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
