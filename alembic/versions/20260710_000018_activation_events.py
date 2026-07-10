"""Add activation events table.

Revision ID: 20260710_000018
Revises: 20260623_000017
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260710_000018"
down_revision = "20260623_000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activation_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("event_name", sa.String(length=32), nullable=False),
        sa.Column("auth_mode", sa.String(length=32), nullable=False),
        sa.Column("device_class", sa.String(length=16), nullable=False),
        sa.Column("reason_class", sa.String(length=32), nullable=True),
        sa.Column("copy_kind", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_name IN ('integration_failed', 'integration_saved', 'token_copied')",
            name="ck_activation_events_event_name",
        ),
        sa.CheckConstraint(
            "auth_mode IN ('domain_api_key', 'user_token', 'unknown')",
            name="ck_activation_events_auth_mode",
        ),
        sa.CheckConstraint(
            "device_class IN ('mobile', 'desktop', 'unknown')",
            name="ck_activation_events_device_class",
        ),
        sa.CheckConstraint(
            "reason_class IS NULL OR reason_class IN "
            "('auth_error', 'host_resolution_error', 'vetmanager_error', "
            "'validation_error', 'csrf_error', 'unknown')",
            name="ck_activation_events_reason_class",
        ),
        sa.CheckConstraint(
            "copy_kind IS NULL OR copy_kind IN ('token', 'config', 'mcp_url', 'unknown')",
            name="ck_activation_events_copy_kind",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activation_events_account_id", "activation_events", ["account_id"])
    op.create_index("ix_activation_events_created_at", "activation_events", ["created_at"])
    op.create_index(
        "ix_activation_events_account_created",
        "activation_events",
        ["account_id", "created_at"],
    )
    op.create_index(
        "ix_activation_events_event_created",
        "activation_events",
        ["event_name", "created_at"],
    )
    op.create_index(
        "ix_activation_events_breakdown_created",
        "activation_events",
        ["event_name", "device_class", "auth_mode", "reason_class", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_activation_events_breakdown_created", table_name="activation_events")
    op.drop_index("ix_activation_events_event_created", table_name="activation_events")
    op.drop_index("ix_activation_events_account_created", table_name="activation_events")
    op.drop_index("ix_activation_events_created_at", table_name="activation_events")
    op.drop_index("ix_activation_events_account_id", table_name="activation_events")
    op.drop_table("activation_events")
