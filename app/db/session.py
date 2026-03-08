# app/db/session.py
"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.settings.config import Config

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None

_DEFAULT_URL = "sqlite+aiosqlite:///workspace/saras.db"


def get_engine():
    global _engine
    if _engine is None:
        url = Config.DATABASE_URL or _DEFAULT_URL
        _engine = create_async_engine(url, echo=False)
        logger.info("DB engine created: %s", url.split("@")[-1] if "@" in url else url)
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def init_db() -> None:
    """Create all tables.

    For development / SQLite fallback. In production use Alembic migrations.
    """
    from app.db.models import Base

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialised.")
