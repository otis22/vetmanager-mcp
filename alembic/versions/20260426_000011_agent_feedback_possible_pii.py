"""Add possible PII flag to agent feedback reports."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_000011"
down_revision = "20260425_000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_feedback_reports",
        sa.Column("possible_pii", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Existing model/user reports were saved before Stage 150 contextual redaction,
    # so mark them for operator spot-check. Auto-events store fixed strings only.
    op.execute("UPDATE agent_feedback_reports SET possible_pii = true WHERE source != 'auto'")
    with op.batch_alter_table("agent_feedback_reports") as batch:
        batch.alter_column(
            "redaction_version",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="2",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_feedback_reports") as batch:
        batch.alter_column(
            "redaction_version",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="1",
        )
    op.drop_column("agent_feedback_reports", "possible_pii")
