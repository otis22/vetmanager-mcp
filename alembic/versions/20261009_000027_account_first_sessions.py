"""Persist the first session for accounts created after release.

Revision ID: 20261009_000027
Revises: 20261002_000026
"""

from alembic import op
import sqlalchemy as sa

revision = "20261009_000027"
down_revision = "20261002_000026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_first_sessions",
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("first_token_issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_tool_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_report_saved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_account_first_sessions_first_token_issued_at", "account_first_sessions", ["first_token_issued_at"])


def downgrade() -> None:
    op.drop_index("ix_account_first_sessions_first_token_issued_at", table_name="account_first_sessions")
    op.drop_table("account_first_sessions")
