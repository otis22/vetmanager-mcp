"""Composite index on token_usage_logs (event_type, event_at).

Stage 111.2 (F3 blocker from super-review 2026-04-19): `collect_metrics`
in `scripts/product_metrics_report.py` makes 7+ serial `SELECT count(*)
FROM token_usage_logs WHERE event_type = X AND event_at >= Y` queries per
run. Without a composite index these degenerate into full table scans as
the table grows (~1.4M rows/day projected on busy tenants); PRD 110's
`<2s on prod` target is violated at 100k+ rows. This migration adds the
index; query text is unchanged — planners on both SQLite and Postgres
pick it up automatically.
"""

from alembic import op


revision = "20260419_000007"
down_revision = "20260407_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_token_usage_logs_event_type_event_at",
        "token_usage_logs",
        ["event_type", "event_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_token_usage_logs_event_type_event_at",
        "token_usage_logs",
    )
