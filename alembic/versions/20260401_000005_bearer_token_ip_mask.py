"""Add allowed_ip_mask to service_bearer_tokens for IP-based access control."""

import sqlalchemy as sa
from alembic import op

revision = "20260401_000005"
down_revision = "20260326_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_bearer_tokens",
        sa.Column("allowed_ip_mask", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_bearer_tokens", "allowed_ip_mask")
