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
    assert "agent_feedback_reports" in table_names
    assert "known_issues" in table_names
    account_columns = {column["name"] for column in inspector.get_columns("accounts")}
    assert "password_hash" in account_columns
    token_columns = {column["name"] for column in inspector.get_columns("service_bearer_tokens")}
    assert "access_policy_version" in token_columns
    assert "is_depersonalized" in token_columns
    assert "scopes_json" in token_columns
    feedback_columns = {column["name"] for column in inspector.get_columns("agent_feedback_reports")}
    assert "error_fingerprint_hash" in feedback_columns
    assert "params_shape_json" in feedback_columns
    assert "possible_pii" in feedback_columns
    known_issue_columns = {column["name"] for column in inspector.get_columns("known_issues")}
    assert "agent_playbook_json" in known_issue_columns
    assert "report_count" in known_issue_columns


def test_agent_feedback_possible_pii_migration_backfills_existing_rows(tmp_path: Path):
    """Stage 150: existing model/user feedback is conservative, auto-events stay safe."""
    from sqlalchemy import text as _text

    config = _make_alembic_config(tmp_path)
    command.upgrade(config, "20260425_000010")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        conn.execute(_text(
            "INSERT INTO agent_feedback_reports "
            "(source, category, severity, status, summary, details, redaction_version) "
            "VALUES "
            "('model', 'bug', 'low', 'new', 'model report', 'details', 1), "
            "('auto', 'bug', 'low', 'new', 'auto report', 'fixed details', 1)"
        ))
        conn.commit()

    command.upgrade(config, "head")

    with engine.connect() as conn:
        rows = conn.execute(_text(
            "SELECT source, possible_pii FROM agent_feedback_reports ORDER BY id"
        )).fetchall()
        columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("agent_feedback_reports")
        }

    assert rows == [("model", True), ("auto", False)]
    assert columns["possible_pii"]["nullable"] is False


def test_depersonalized_flag_migration_defaults_existing_tokens_to_false(tmp_path: Path):
    """Upgrade must keep legacy tokens standard when adding depersonalization policy."""
    from sqlalchemy import text as _text

    config = _make_alembic_config(tmp_path)
    command.upgrade(config, "20260419_000007")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        conn.execute(_text(
            "INSERT INTO accounts (email, password_hash, status, created_at, updated_at) "
            "VALUES ('legacy@example.com', 'hash', 'active', datetime('now'), datetime('now'))"
        ))
        conn.commit()
        account_id = conn.execute(_text(
            "SELECT id FROM accounts WHERE email = 'legacy@example.com'"
        )).fetchone()[0]
        conn.execute(_text(
            f"INSERT INTO service_bearer_tokens (account_id, name, token_prefix, token_hash, status, created_at) "
            f"VALUES ({account_id}, 'legacy', 'sbt_legacy', 'hash999', 'active', datetime('now'))"
        ))
        conn.commit()

    command.upgrade(config, "head")

    with engine.connect() as conn:
        row = conn.execute(_text(
            "SELECT is_depersonalized FROM service_bearer_tokens WHERE name = 'legacy'"
        )).fetchone()

    assert row is not None
    assert row[0] in (0, False)


def test_frontdesk_scope_backfill_adds_analytics_read_to_exact_stage130_bundle(tmp_path: Path):
    """Upgrade should fix already-issued frontdesk tokens without touching non-exact bundles."""
    import json
    from sqlalchemy import text as _text

    old_frontdesk = json.dumps([
        "admissions.read",
        "admissions.write",
        "clients.read",
        "clients.write",
        "finance.read",
        "messaging.write",
        "pets.read",
        "pets.write",
        "reference.read",
        "users.read",
    ], separators=(",", ":"))
    new_frontdesk = json.dumps([
        "admissions.read",
        "admissions.write",
        "analytics.read",
        "clients.read",
        "clients.write",
        "finance.read",
        "messaging.write",
        "pets.read",
        "pets.write",
        "reference.read",
        "users.read",
    ])
    custom = json.dumps(["clients.read", "pets.read"])

    config = _make_alembic_config(tmp_path)
    command.upgrade(config, "20260423_000008")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        conn.execute(_text(
            "INSERT INTO accounts (email, password_hash, status, created_at, updated_at) "
            "VALUES ('frontdesk@example.com', 'hash', 'active', datetime('now'), datetime('now'))"
        ))
        account_id = conn.execute(_text(
            "SELECT id FROM accounts WHERE email = 'frontdesk@example.com'"
        )).fetchone()[0]
        conn.execute(
            _text(
                "INSERT INTO service_bearer_tokens "
                "(account_id, name, token_prefix, token_hash, status, scopes_json, created_at) "
                "VALUES (:account_id, :name, :prefix, :hash, 'active', :scopes_json, datetime('now'))"
            ),
            [
                {
                    "account_id": account_id,
                    "name": "frontdesk",
                    "prefix": "vm_st_front",
                    "hash": "hash-front",
                    "scopes_json": old_frontdesk,
                },
                {
                    "account_id": account_id,
                    "name": "custom",
                    "prefix": "vm_st_custom",
                    "hash": "hash-custom",
                    "scopes_json": custom,
                },
            ],
        )
        conn.commit()

    command.upgrade(config, "head")

    with engine.connect() as conn:
        rows = dict(conn.execute(_text(
            "SELECT name, scopes_json FROM service_bearer_tokens ORDER BY name"
        )).fetchall())

    assert json.loads(rows["frontdesk"]) == json.loads(new_frontdesk)
    assert rows["custom"] == custom


def test_status_check_constraints_reject_invalid_values(tmp_path: Path):
    """CHECK constraints must reject invalid status values for accounts, connections, tokens."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    config = _make_alembic_config(tmp_path)
    command.upgrade(config, "head")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    # SQLite needs PRAGMA to enforce CHECK constraints by default it does enforce them.
    with engine.connect() as conn:
        from sqlalchemy import text as _text
        # Insert valid account status — must succeed
        conn.execute(_text(
            "INSERT INTO accounts (email, password_hash, status, created_at, updated_at) "
            "VALUES ('valid@example.com', 'hash', 'active', datetime('now'), datetime('now'))"
        ))
        conn.commit()

        # Insert invalid account status — must fail
        with pytest.raises(IntegrityError):
            conn.execute(_text(
                "INSERT INTO accounts (email, password_hash, status, created_at, updated_at) "
                "VALUES ('invalid@example.com', 'hash', 'bogus', datetime('now'), datetime('now'))"
            ))
            conn.commit()
        conn.rollback()

        # Get valid account_id
        row = conn.execute(_text("SELECT id FROM accounts WHERE email = 'valid@example.com'")).fetchone()
        account_id = row[0]

        # Insert valid connection status
        conn.execute(_text(
            f"INSERT INTO vetmanager_connections (account_id, auth_mode, status, created_at, updated_at) "
            f"VALUES ({account_id}, 'domain_api_key', 'active', datetime('now'), datetime('now'))"
        ))
        conn.commit()

        # Insert invalid connection status
        with pytest.raises(IntegrityError):
            conn.execute(_text(
                f"INSERT INTO vetmanager_connections (account_id, auth_mode, status, created_at, updated_at) "
                f"VALUES ({account_id}, 'domain_api_key', 'pending', datetime('now'), datetime('now'))"
            ))
            conn.commit()
        conn.rollback()

        # Insert invalid token status
        with pytest.raises(IntegrityError):
            conn.execute(_text(
                f"INSERT INTO service_bearer_tokens (account_id, name, token_prefix, token_hash, status, created_at) "
                f"VALUES ({account_id}, 'test', 'sbt_test', 'hash123', 'pending', datetime('now'))"
            ))
            conn.commit()
        conn.rollback()


def test_status_check_migration_normalizes_legacy_invalid_data(tmp_path: Path):
    """Migration must normalize pre-existing invalid status values across all 3 tables."""
    from sqlalchemy import text as _text

    config = _make_alembic_config(tmp_path)
    # Upgrade only to the migration BEFORE check constraints (revision 5)
    command.upgrade(config, "20260401_000005")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        # Insert legacy rows with bogus statuses across all 3 tables
        conn.execute(_text(
            "INSERT INTO accounts (email, password_hash, status, created_at, updated_at) "
            "VALUES ('legacy@example.com', 'hash', 'pending_review', datetime('now'), datetime('now'))"
        ))
        conn.commit()
        account_id = conn.execute(_text(
            "SELECT id FROM accounts WHERE email = 'legacy@example.com'"
        )).fetchone()[0]
        conn.execute(_text(
            f"INSERT INTO vetmanager_connections (account_id, auth_mode, status, created_at, updated_at) "
            f"VALUES ({account_id}, 'domain_api_key', 'orphaned', datetime('now'), datetime('now'))"
        ))
        conn.execute(_text(
            f"INSERT INTO service_bearer_tokens (account_id, name, token_prefix, token_hash, status, created_at) "
            f"VALUES ({account_id}, 'legacy', 'sbt_legacy', 'hash999', 'pending', datetime('now'))"
        ))
        conn.commit()

    # Now upgrade to head — should not fail; should normalize all bad rows
    command.upgrade(config, "head")

    with engine.connect() as conn:
        # Account: invalid → 'active'
        assert conn.execute(_text(
            "SELECT status FROM accounts WHERE email = 'legacy@example.com'"
        )).fetchone()[0] == "active"
        # Connection: invalid → 'disabled'
        assert conn.execute(_text(
            "SELECT status FROM vetmanager_connections WHERE auth_mode = 'domain_api_key'"
        )).fetchone()[0] == "disabled"
        # Token: invalid → 'disabled'
        assert conn.execute(_text(
            "SELECT status FROM service_bearer_tokens WHERE name = 'legacy'"
        )).fetchone()[0] == "disabled"


def test_postgres_url_is_normalized_for_migrations():
    """Alembic should receive a sync SQLAlchemy URL even if runtime uses async."""
    assert (
        storage.normalize_database_url_for_migrations(
            "postgresql+asyncpg://user:pass@db/app"
        )
        == "postgresql://user:pass@db/app"
    )
