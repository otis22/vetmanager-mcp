"""Add indexes on foreign key columns for query performance."""

from alembic import op


revision = "20260326_000004"
down_revision = "20260321_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_vetmanager_connections_account_id",
        "vetmanager_connections",
        ["account_id"],
    )
    op.create_index(
        "ix_service_bearer_tokens_account_id",
        "service_bearer_tokens",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_service_bearer_tokens_account_id", "service_bearer_tokens")
    op.drop_index("ix_vetmanager_connections_account_id", "vetmanager_connections")
