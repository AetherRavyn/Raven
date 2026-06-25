# app/db/session.py
"""Async SQLAlchemy engine and session factory (SQLite only)."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.settings.config import Config

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None

_DEFAULT_URL = "sqlite+aiosqlite:///workspace/raven.db"


def get_engine():
    global _engine
    if _engine is None:
        db_path = Path(Config.GRAPH_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+aiosqlite:///{db_path}"
        _engine = create_async_engine(url, echo=False)
        logger.info("DB engine created: %s", db_path)
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def init_db() -> None:
    """Create all tables."""
    from app.db.models import Base

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialised.")
