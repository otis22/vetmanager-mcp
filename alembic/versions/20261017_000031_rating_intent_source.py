"""Track whether a Report AI rating intent came from job creation.

Revision ID: 20261017_000031
Revises: 20261016_000030
"""

from alembic import op
import sqlalchemy as sa

revision = "20261017_000031"
down_revision = "20261016_000030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("report_ai_job_ratings") as batch_op:
        batch_op.add_column(sa.Column(
            "intent_from_create", sa.Boolean(), nullable=False,
            server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("report_ai_job_ratings") as batch_op:
        batch_op.drop_column("intent_from_create")
