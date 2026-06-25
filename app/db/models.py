# app/db/models.py
"""SQLAlchemy ORM models for RAVEN persistent storage."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32))
    platform_user_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    preferred_language: Mapped[str] = mapped_column(String(16), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    memories: Mapped[list["Memory"]] = relationship(back_populates="user")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(32))  # FACT | RULE | TOOL_GUIDE
    content: Mapped[str] = mapped_column(Text)
    # Vector column: populated when memory backend is active.
    # Stored as JSON array in SQLite.
    embedding_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    importance: Mapped[float] = mapped_column(Float, default=1.0)

    user: Mapped[Optional["User"]] = relationship(back_populates="memories")


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), unique=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    platform: Mapped[str] = mapped_column(String(32))
    chat_id: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    cron_expression: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
