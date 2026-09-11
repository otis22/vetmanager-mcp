"""Mark dashboard-originated human feedback explicitly.

Revision ID: 20260912_000022
Revises: 20260911_000021
"""

from alembic import op
import sqlalchemy as sa


revision = "20260912_000022"
down_revision = "20260911_000021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_feedback_reports") as batch:
        batch.add_column(
            sa.Column("is_human_web_submission", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_feedback_reports") as batch:
        batch.drop_column("is_human_web_submission")
