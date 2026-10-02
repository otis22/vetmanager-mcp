"""Guard the SQLAlchemy 2.1 installation and the Alembic driver split."""

import importlib.metadata
from pathlib import Path
import tomllib

from sqlalchemy import create_engine

import storage


ROOT = Path(__file__).resolve().parents[1]


def test_sqlalchemy_21_async_dependency_in_both_install_sources():
    version = importlib.metadata.version("sqlalchemy")
    assert (2, 1) <= tuple(map(int, version.split(".")[:2])) < (2, 2)
    import greenlet  # noqa: F401 - async SQLAlchemy needs this at runtime

    expected = "sqlalchemy[asyncio]>=2.1,<2.2"
    docker_base = (ROOT / "Dockerfile").read_text().split("FROM base AS production", 1)[0]
    project_dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert f'"{expected}"' in docker_base
    assert expected in project_dependencies
    assert '"psycopg2-binary>=2.9.0,<3"' in docker_base
    assert "psycopg2-binary>=2.9.0,<3" in project_dependencies


def test_migrations_use_installed_sync_driver_for_every_postgres_url():
    for runtime_url in (
        "postgresql+asyncpg://user:pass@db/app",
        "postgresql://user:pass@db/app",
        "postgres://user:pass@db/app",
        "postgresql+psycopg2://user:pass@db/app",
    ):
        migration_url = storage.normalize_database_url_for_migrations(runtime_url)
        assert migration_url == "postgresql+psycopg2://user:pass@db/app"
        engine = create_engine(migration_url)
        try:
            assert engine.dialect.driver == "psycopg2"
        finally:
            engine.dispose()

    assert storage.normalize_database_url_for_migrations("sqlite+aiosqlite:///:memory:") == "sqlite:///:memory:"
