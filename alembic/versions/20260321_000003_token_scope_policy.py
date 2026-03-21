"""Add future scope policy metadata to bearer tokens."""

from alembic import op
import sqlalchemy as sa


revision = "20260321_000003"
down_revision = "20260321_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_bearer_tokens",
        sa.Column(
            "access_policy_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "service_bearer_tokens",
        sa.Column("scopes_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_bearer_tokens", "scopes_json")
    op.drop_column("service_bearer_tokens", "access_policy_version")
