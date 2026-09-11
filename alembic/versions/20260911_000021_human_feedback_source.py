"""Allow human-originated feedback reports.

Revision ID: 20260911_000021
Revises: 20260826_000020
"""

from alembic import op
import sqlalchemy as sa
import re


revision = "20260911_000021"
down_revision = "20260826_000020"
branch_labels = None
depends_on = None

_TABLE = "agent_feedback_reports"
_NEW = "source IN ('model', 'auto', 'human', 'user_complaint')"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        constraints = sa.inspect(bind).get_check_constraints(_TABLE)
        source_constraints = [
            item for item in constraints
            if re.search(r"\bsource\b", str(item.get("sqltext") or ""), re.IGNORECASE)
        ]
        if any(not item.get("name") for item in source_constraints):
            raise RuntimeError("stage 315: unnamed source CHECK cannot be safely replaced")
        with op.batch_alter_table(_TABLE) as batch:
            for constraint in source_constraints:
                batch.drop_constraint(constraint["name"], type_="check")
            batch.create_check_constraint("ck_agent_feedback_reports_source", _NEW)
        return
    names = bind.execute(sa.text("""
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'agent_feedback_reports'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ~* '(^|[^a-z_])source([^a-z_]|$)'
    """)).scalars().all()
    if len(names) > 1:
        raise RuntimeError("stage 315: multiple source CHECK constraints require manual review")
    if names:
        op.drop_constraint(names[0], _TABLE, type_="check")
    op.create_check_constraint("ck_agent_feedback_reports_source", _TABLE, _NEW)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint("ck_agent_feedback_reports_source", type_="check")
        batch.create_check_constraint(
            "ck_agent_feedback_reports_source",
            "source IN ('model', 'auto', 'user_complaint')",
        )
