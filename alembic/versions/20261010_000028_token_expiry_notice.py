"""Add rolling expiry notice claim to per-token usage stats.

Revision ID: 20261010_000028
Revises: 20261009_000027
"""

from alembic import op
import sqlalchemy as sa

revision = "20261010_000028"
down_revision = "20261009_000027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("token_usage_stats", sa.Column("expiry_notice_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("token_usage_stats", "expiry_notice_at")
