"""Add password hash to accounts for web authentication."""

from alembic import op
import sqlalchemy as sa


revision = "20260321_000002"
down_revision = "20260321_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("password_hash", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "password_hash")
