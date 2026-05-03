"""Stage 158: add soft-archive marker for accounts."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_000014"
down_revision = "20260503_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_accounts_archived_at", ["archived_at"])


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_index("ix_accounts_archived_at")
        batch.drop_column("archived_at")
