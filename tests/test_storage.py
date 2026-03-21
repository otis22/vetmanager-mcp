"""Unit tests for stage 21 storage foundation."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import storage


def test_default_database_url_uses_sqlite_aiosqlite(monkeypatch: pytest.MonkeyPatch):
    """Local default must be SQLite over aiosqlite for zero-setup dev/test."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert storage.get_database_url() == "sqlite+aiosqlite:///./data/vetmanager.db"


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (
            "postgresql://user:pass@db/app",
            "postgresql+asyncpg://user:pass@db/app",
        ),
        (
            "postgres://user:pass@db/app",
            "postgresql+asyncpg://user:pass@db/app",
        ),
        (
            "sqlite:///./tmp/app.db",
            "sqlite+aiosqlite:///./tmp/app.db",
        ),
        (
            "sqlite:///:memory:",
            "sqlite+aiosqlite:///:memory:",
        ),
    ],
)
def test_normalize_database_url_converts_supported_sync_schemes(
    raw_url: str,
    expected: str,
):
    """Storage must normalize sync-style URLs into async SQLAlchemy URLs."""
    assert storage.normalize_database_url(raw_url) == expected


@pytest.mark.asyncio
async def test_initialize_storage_creates_sqlite_file_and_session_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Bootstrap should create local SQLite path and expose AsyncSession factory."""
    database_path = tmp_path / "state" / "vetmanager.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    storage.reset_storage_state()

    await storage.initialize_storage()
    session_factory = storage.get_session_factory()

    assert database_path.exists()
    async with session_factory() as session:
        assert isinstance(session, AsyncSession)


@pytest.mark.asyncio
async def test_reset_storage_state_disposes_cached_engine_in_async_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Async tests should fully dispose cached SQLite engine before loop shutdown."""
    database_path = tmp_path / "state" / "dispose.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    storage.reset_storage_state()
    await storage.initialize_storage()
    engine = storage.get_engine()

    dispose_called = asyncio.Event()
    original_dispose = type(engine).dispose

    async def tracked_dispose(self, *args, **kwargs):
        if self is engine:
            dispose_called.set()
        return await original_dispose(self, *args, **kwargs)

    monkeypatch.setattr(type(engine), "dispose", tracked_dispose)

    storage.reset_storage_state()

    assert dispose_called.is_set()


@pytest.mark.asyncio
async def test_bootstrap_storage_schema_creates_fresh_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Fresh local runtime should bootstrap metadata tables before web usage."""
    database_path = tmp_path / "state" / "bootstrap.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    storage.reset_storage_state()

    await storage.initialize_storage()
    await storage.bootstrap_storage_schema()

    async with storage.get_engine().begin() as conn:
        rows = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
        )

    assert rows.scalar_one() == "accounts"
