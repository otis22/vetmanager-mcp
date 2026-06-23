"""Stage 178: store OAuth personal-data privacy marker."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260623_000017"
down_revision = "20260622_000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_grants", sa.Column("is_depersonalized", sa.Boolean(), nullable=True))
    op.add_column("oauth_authorization_codes", sa.Column("is_depersonalized", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_authorization_codes", "is_depersonalized")
    op.drop_column("oauth_grants", "is_depersonalized")
