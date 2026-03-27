"""Async storage foundation for the bearer-service roadmap stages."""

from __future__ import annotations

import asyncio
import os
import threading
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/vetmanager.db"


class StorageError(RuntimeError):
    """Raised when the persistence layer cannot be initialized safely."""


class Base(DeclarativeBase):
    """Declarative base for future bearer-service models."""


def normalize_database_url(raw_url: str | None) -> str:
    """Normalize configured database URL to an async SQLAlchemy URL."""
    if not raw_url:
        return DEFAULT_DATABASE_URL
    if raw_url.startswith("postgres://"):
        return "postgresql+asyncpg://" + raw_url[len("postgres://") :]
    if raw_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + raw_url[len("postgresql://") :]
    if raw_url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + raw_url[len("sqlite:///") :]
    return raw_url


def normalize_database_url_for_migrations(raw_url: str | None) -> str:
    """Normalize configured database URL to a sync URL suitable for Alembic."""
    normalized_url = normalize_database_url(raw_url)
    if normalized_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + normalized_url[len("postgresql+asyncpg://") :]
    if normalized_url.startswith("sqlite+aiosqlite:///"):
        return "sqlite:///" + normalized_url[len("sqlite+aiosqlite:///") :]
    return normalized_url


def get_database_url() -> str:
    """Return normalized DATABASE_URL with a safe local default."""
    return normalize_database_url(os.environ.get("DATABASE_URL"))


def _ensure_sqlite_path(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    if url.database in (None, "", ":memory:"):
        return
    db_path = Path(url.database)
    db_path.parent.mkdir(parents=True, exist_ok=True)


def create_database_engine(database_url: str | None = None) -> AsyncEngine:
    """Create async engine for the configured database."""
    normalized_url = normalize_database_url(database_url)
    _ensure_sqlite_path(normalized_url)

    kwargs: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }

    if normalized_url.startswith("postgresql"):
        kwargs.update({
            "pool_size": int(os.environ.get("DB_POOL_SIZE", "10")),
            "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "20")),
            "pool_timeout": 30,
            "pool_recycle": 1800,
        })

    return create_async_engine(normalized_url, **kwargs)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return process-level async engine for storage access."""
    return create_database_engine(get_database_url())


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return cached async session factory bound to the configured engine."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def initialize_storage() -> None:
    """Validate the configured DB connection and bootstrap local SQLite path."""
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise StorageError("Failed to initialize storage backend.") from exc


async def bootstrap_storage_schema() -> None:
    """Create current metadata tables for fresh local runtimes if they do not exist."""
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except SQLAlchemyError as exc:
        raise StorageError("Failed to bootstrap storage schema.") from exc


def reset_storage_state() -> None:
    """Clear cached engine/session objects and dispose old engine if present."""
    cached_engine: AsyncEngine | None = None
    cache_info = get_engine.cache_info()
    if cache_info.currsize:
        cached_engine = get_engine()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    if cached_engine is None:
        return

    def _dispose_engine() -> None:
        asyncio.run(cached_engine.dispose())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        _dispose_engine()
        return

    worker = threading.Thread(target=_dispose_engine, name="storage-engine-dispose", daemon=True)
    worker.start()
    worker.join()
