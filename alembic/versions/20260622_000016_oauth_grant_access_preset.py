"""Stage 177: store OAuth grant access preset marker."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260622_000016"
down_revision = "20260622_000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_grants", sa.Column("access_preset", sa.String(length=32), nullable=True))
    op.add_column("oauth_authorization_codes", sa.Column("access_preset", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_authorization_codes", "access_preset")
    op.drop_column("oauth_grants", "access_preset")
