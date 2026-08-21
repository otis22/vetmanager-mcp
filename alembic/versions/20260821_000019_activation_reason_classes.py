"""Expand activation reason classes while retaining legacy events.

Revision ID: 20260821_000019
Revises: 20260710_000018
Create Date: 2026-08-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260821_000019"
down_revision = "20260710_000018"
branch_labels = None
depends_on = None

_LEGACY = "'auth_error', 'host_resolution_error', 'vetmanager_error', 'validation_error', 'unknown'"
_EXPANDED = "'auth_error', 'host_resolution_error', 'upstream_4xx', 'upstream_5xx', 'network', 'internal', 'vetmanager_error', 'validation_error', 'unknown'"
_NEW_VALUES = ("upstream_4xx", "upstream_5xx", "network", "internal")


def _replace_constraint(values: str) -> None:
    with op.batch_alter_table("activation_events") as batch_op:
        batch_op.drop_constraint("ck_activation_events_reason_class", type_="check")
        batch_op.create_check_constraint(
            "ck_activation_events_reason_class",
            f"reason_class IS NULL OR reason_class IN ({values})",
        )


def upgrade() -> None:
    _replace_constraint(_EXPANDED)


def downgrade() -> None:
    activation_events = sa.table("activation_events", sa.column("reason_class", sa.String()))
    op.execute(
        activation_events.update()
        .where(activation_events.c.reason_class.in_(_NEW_VALUES))
        .values(reason_class="vetmanager_error")
    )
    _replace_constraint(_LEGACY)
