"""Enforce one active Vetmanager connection per account.

Revision ID: 20260917_000024
Revises: 20260912_000023
"""

from alembic import op
import sqlalchemy as sa


revision = "20260917_000024"
down_revision = "20260912_000023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    duplicates = op.get_bind().execute(sa.text(
        "SELECT account_id FROM vetmanager_connections "
        "WHERE status = 'active' GROUP BY account_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicates is not None:
        raise RuntimeError("Cannot enforce one active Vetmanager connection: duplicate active rows exist.")
    op.create_index(
        "uq_vetmanager_connections_one_active_account",
        "vetmanager_connections",
        ["account_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_vetmanager_connections_one_active_account", table_name="vetmanager_connections")
