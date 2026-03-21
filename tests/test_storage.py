"""Unit tests for stage 21 storage foundation."""

from pathlib import Path

import pytest
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
