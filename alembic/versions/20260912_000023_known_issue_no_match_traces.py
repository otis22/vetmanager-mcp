"""Persist bounded privacy-safe known-issue no-match traces.

Revision ID: 20260912_000023
Revises: 20260912_000022
"""

from alembic import op
import sqlalchemy as sa


revision = "20260912_000023"
down_revision = "20260912_000022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "known_issue_no_match_traces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("related_tool", sa.String(length=128), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("normalized_error_text", sa.Text(), nullable=False),
        sa.Column("possible_pii", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_known_issue_no_match_traces_tool_created", "known_issue_no_match_traces", ["related_tool", "created_at"])
    op.create_index("ix_known_issue_no_match_traces_created", "known_issue_no_match_traces", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_known_issue_no_match_traces_created", table_name="known_issue_no_match_traces")
    op.drop_index("ix_known_issue_no_match_traces_tool_created", table_name="known_issue_no_match_traces")
    op.drop_table("known_issue_no_match_traces")
