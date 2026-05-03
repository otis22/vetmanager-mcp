"""Stage 155: backfill NULL allowed_ip_mask to '*.*.*.*' and enforce NOT NULL."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_000013"
down_revision = "20260502_000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill any legacy NULL masks (these previously meant "unrestricted"
    # via ServiceBearerToken.get_allowed_ip_mask()) with the explicit literal
    # so the column can become NOT NULL without changing operational behavior.
    op.execute(
        "UPDATE service_bearer_tokens SET allowed_ip_mask = '*.*.*.*' "
        "WHERE allowed_ip_mask IS NULL"
    )
    # batch_alter_table for SQLite compatibility (the project's test suite
    # runs on SQLite; PostgreSQL uses the underlying ALTER COLUMN directly).
    with op.batch_alter_table("service_bearer_tokens") as batch:
        batch.alter_column(
            "allowed_ip_mask",
            existing_type=sa.String(64),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("service_bearer_tokens") as batch:
        batch.alter_column(
            "allowed_ip_mask",
            existing_type=sa.String(64),
            nullable=True,
        )
    # No reverse backfill: previously-NULL rows stay '*.*.*.*' (semantic
    # equivalent of the old `get_allowed_ip_mask()` fallback). Downgrade is
    # an emergency operation; loss of NULL-vs-explicit-wildcard distinction
    # is acceptable.
