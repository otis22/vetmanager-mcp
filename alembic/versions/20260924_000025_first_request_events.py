"""Permit bounded first-request motivation events.

Revision ID: 20260924_000025
Revises: 20260917_000024
"""

from alembic import op
import sqlalchemy as sa

revision = "20260924_000025"
down_revision = "20260917_000024"
branch_labels = None
depends_on = None

_OLD = "'integration_failed', 'integration_saved', 'token_copied'"
_NEW = _OLD + ", 'motivator_shown', 'example_copied'"


def _replace(values: str) -> None:
    with op.batch_alter_table("activation_events") as batch_op:
        batch_op.drop_constraint("ck_activation_events_event_name", type_="check")
        batch_op.create_check_constraint(
            "ck_activation_events_event_name", f"event_name IN ({values})"
        )


def upgrade() -> None:
    _replace(_NEW)


def downgrade() -> None:
    events = sa.table("activation_events", sa.column("event_name", sa.String()))
    op.execute(events.delete().where(events.c.event_name.in_(("motivator_shown", "example_copied"))))
    _replace(_OLD)
