"""Durable cache versions and active write fences for three MCP slots.

Revision ID: 20261014_000029
Revises: 20261010_000028
"""

from alembic import op
import sqlalchemy as sa

revision = "20261014_000029"
down_revision = "20261010_000028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vetmanager_cache_barriers",
        sa.Column("tag_hash", sa.String(length=64), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("active_writes", sa.Integer(), nullable=False),
        sa.CheckConstraint("generation >= 0", name="ck_vm_cache_generation"),
        sa.CheckConstraint("active_writes >= 0", name="ck_vm_cache_active_writes"),
    )


def downgrade() -> None:
    op.drop_table("vetmanager_cache_barriers")
