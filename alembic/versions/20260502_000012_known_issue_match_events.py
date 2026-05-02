"""Add known_issue_match_events table for Stage 151 analytics."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260502_000012"
down_revision = "20260426_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "known_issue_match_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("known_issue_id", sa.Integer(), nullable=False),
        sa.Column("related_tool", sa.String(length=128), nullable=True),
        sa.Column("error_fingerprint_hash", sa.String(length=96), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("bearer_token_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["known_issue_id"],
            ["known_issues.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bearer_token_id"],
            ["service_bearer_tokens.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "source IN ('injection', 'report', 'auto')",
            name="ck_known_issue_match_events_source",
        ),
    )
    op.create_index(
        "ix_known_issue_match_events_known_issue_created",
        "known_issue_match_events",
        ["known_issue_id", "created_at"],
    )
    op.create_index(
        "ix_known_issue_match_events_account_created",
        "known_issue_match_events",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_known_issue_match_events_account_created",
        table_name="known_issue_match_events",
    )
    op.drop_index(
        "ix_known_issue_match_events_known_issue_created",
        table_name="known_issue_match_events",
    )
    op.drop_table("known_issue_match_events")
