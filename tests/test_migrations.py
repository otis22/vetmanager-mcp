"""Tests for stage 21.2 database migrations."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

import storage


def _make_alembic_config(tmp_path: Path) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    database_url = f"sqlite:///{tmp_path / 'migration-test.db'}"
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        storage.normalize_database_url_for_migrations(database_url),
    )
    return config


def test_alembic_upgrade_creates_bearer_service_tables(tmp_path: Path):
    """Baseline migration must create the planned bearer-service tables."""
    config = _make_alembic_config(tmp_path)
    command.upgrade(config, "head")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "accounts" in table_names
    assert "vetmanager_connections" in table_names
    assert "service_bearer_tokens" in table_names
    assert "token_usage_stats" in table_names
    assert "token_usage_logs" in table_names
    account_columns = {column["name"] for column in inspector.get_columns("accounts")}
    assert "password_hash" in account_columns


def test_postgres_url_is_normalized_for_migrations():
    """Alembic should receive a sync SQLAlchemy URL even if runtime uses async."""
    assert (
        storage.normalize_database_url_for_migrations(
            "postgresql+asyncpg://user:pass@db/app"
        )
        == "postgresql://user:pass@db/app"
    )
