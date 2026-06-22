"""Stage 173: add OAuth tables for ChatGPT connector."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260622_000015"
down_revision = "20260503_000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(length=96), nullable=False),
        sa.Column("client_name", sa.String(length=240), nullable=True),
        sa.Column("redirect_uris_json", sa.Text(), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(length=32), nullable=False),
        sa.Column("grant_types_json", sa.Text(), nullable=False),
        sa.Column("response_types_json", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_oauth_clients_status"),
        sa.UniqueConstraint("client_id", name="uq_oauth_clients_client_id"),
    )
    op.create_index("ix_oauth_clients_status_created", "oauth_clients", ["status", "created_at"])

    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "vetmanager_connection_id",
            sa.Integer(),
            sa.ForeignKey("vetmanager_connections.id"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(length=96), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=128), nullable=True),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_oauth_grants_status"),
    )
    op.create_index("ix_oauth_grants_account_id", "oauth_grants", ["account_id"])
    op.create_index("ix_oauth_grants_client_id", "oauth_grants", ["client_id"])
    op.create_index("ix_oauth_grants_connection_status", "oauth_grants", ["vetmanager_connection_id", "status"])
    op.create_index("ix_oauth_grants_account_status", "oauth_grants", ["account_id", "status"])

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code_prefix", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=96), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(length=160), nullable=False),
        sa.Column("code_challenge_method", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "vetmanager_connection_id",
            sa.Integer(),
            sa.ForeignKey("vetmanager_connections.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'consumed', 'expired')",
            name="ck_oauth_authorization_codes_status",
        ),
        sa.UniqueConstraint("code_hash", name="uq_oauth_authorization_codes_code_hash"),
    )
    op.create_index("ix_oauth_authorization_codes_account_id", "oauth_authorization_codes", ["account_id"])
    op.create_index("ix_oauth_authorization_codes_client_id", "oauth_authorization_codes", ["client_id"])
    op.create_index(
        "ix_oauth_authorization_codes_vetmanager_connection_id",
        "oauth_authorization_codes",
        ["vetmanager_connection_id"],
    )
    op.create_index(
        "ix_oauth_authorization_codes_client_status",
        "oauth_authorization_codes",
        ["client_id", "status"],
    )
    op.create_index("ix_oauth_authorization_codes_expires", "oauth_authorization_codes", ["expires_at"])

    op.create_table(
        "oauth_access_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("grant_id", sa.Integer(), sa.ForeignKey("oauth_grants.id"), nullable=False),
        sa.Column("token_prefix", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'revoked', 'expired')", name="ck_oauth_access_tokens_status"),
        sa.UniqueConstraint("token_hash", name="uq_oauth_access_tokens_token_hash"),
    )
    op.create_index("ix_oauth_access_tokens_grant_id", "oauth_access_tokens", ["grant_id"])
    op.create_index("ix_oauth_access_tokens_grant_status", "oauth_access_tokens", ["grant_id", "status"])
    op.create_index("ix_oauth_access_tokens_expires", "oauth_access_tokens", ["expires_at"])

    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("grant_id", sa.Integer(), sa.ForeignKey("oauth_grants.id"), nullable=False),
        sa.Column("token_prefix", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_token_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'revoked', 'expired')", name="ck_oauth_refresh_tokens_status"),
        sa.UniqueConstraint("token_hash", name="uq_oauth_refresh_tokens_token_hash"),
    )
    op.create_index("ix_oauth_refresh_tokens_grant_id", "oauth_refresh_tokens", ["grant_id"])
    op.create_index("ix_oauth_refresh_tokens_grant_status", "oauth_refresh_tokens", ["grant_id", "status"])
    op.create_index("ix_oauth_refresh_tokens_expires", "oauth_refresh_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_oauth_refresh_tokens_expires", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_tokens_grant_status", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_tokens_grant_id", table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")

    op.drop_index("ix_oauth_access_tokens_expires", table_name="oauth_access_tokens")
    op.drop_index("ix_oauth_access_tokens_grant_status", table_name="oauth_access_tokens")
    op.drop_index("ix_oauth_access_tokens_grant_id", table_name="oauth_access_tokens")
    op.drop_table("oauth_access_tokens")

    op.drop_index("ix_oauth_authorization_codes_expires", table_name="oauth_authorization_codes")
    op.drop_index("ix_oauth_authorization_codes_client_status", table_name="oauth_authorization_codes")
    op.drop_index(
        "ix_oauth_authorization_codes_vetmanager_connection_id",
        table_name="oauth_authorization_codes",
    )
    op.drop_index("ix_oauth_authorization_codes_client_id", table_name="oauth_authorization_codes")
    op.drop_index("ix_oauth_authorization_codes_account_id", table_name="oauth_authorization_codes")
    op.drop_table("oauth_authorization_codes")

    op.drop_index("ix_oauth_grants_account_status", table_name="oauth_grants")
    op.drop_index("ix_oauth_grants_connection_status", table_name="oauth_grants")
    op.drop_index("ix_oauth_grants_client_id", table_name="oauth_grants")
    op.drop_index("ix_oauth_grants_account_id", table_name="oauth_grants")
    op.drop_table("oauth_grants")

    op.drop_index("ix_oauth_clients_status_created", table_name="oauth_clients")
    op.drop_table("oauth_clients")
