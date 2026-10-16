"""Store sanitized Report AI job intents and agent ratings.

Revision ID: 20261016_000030
Revises: 20261014_000029
"""

from alembic import op
import sqlalchemy as sa

revision = "20261016_000030"
down_revision = "20261014_000029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_ai_job_ratings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("intent_text", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("account_id", "connection_id", "domain", "job_id",
                            name="uq_report_ai_job_ratings_owner_job"),
        sa.CheckConstraint("score IS NULL OR score BETWEEN 1 AND 10",
                           name="ck_report_ai_job_ratings_score"),
    )
    op.create_index("ix_report_ai_job_ratings_created_at", "report_ai_job_ratings", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_report_ai_job_ratings_created_at", table_name="report_ai_job_ratings")
    op.drop_table("report_ai_job_ratings")
