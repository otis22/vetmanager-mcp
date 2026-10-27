"""Add durable per-account stale OAuth refresh marker."""

from alembic import op
import sqlalchemy as sa

revision = "20261026_000033"
down_revision = "20261020_000032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column(
        "oauth_stale_refresh_marked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "oauth_stale_refresh_marked_at")
