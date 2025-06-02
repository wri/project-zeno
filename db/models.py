from __future__ import annotations

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from pydantic import BaseModel, ConfigDict, field_validator, alias_generators
from datetime import datetime


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
        DateTime, nullable=False, default=datetime.now(), onupdate=datetime.now()
    )
    user = relationship("UserOrm", back_populates="threads", foreign_keys=[user_id])


class MessageOrm(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, unique=True, nullable=False)
    thread_id = Column(String, ForeignKey("threads.id"), nullable=False)
    content = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now())
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now(), onupdate=datetime.now()
    )
    thread = relationship(
        "ThreadOrm", back_populates="messages", foreign_keys=[thread_id]
    )


class MessageModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    thread_id: str
    content: dict
    created_at: datetime
    updated_at: datetime
    # thread: ThreadModel


class ThreadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    agent_id: str
    created_at: datetime
    updated_at: datetime
    content: dict
    messages: list[MessageModel] = []
    # user: UserModel


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
