"""Index bounded account activity probes without blocking PostgreSQL writes.

Revision ID: 20261002_000026
Revises: 20260924_000025
"""

from alembic import op
import sqlalchemy as sa

revision = "20261002_000026"
down_revision = "20260924_000025"
branch_labels = None
depends_on = None

_INDEX = "ix_token_usage_logs_account_event_at"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _postgres():
        # CONCURRENTLY cannot run inside Alembic's normal DDL transaction.
        with op.get_context().autocommit_block():
            op.execute("SET lock_timeout = '5s'")
            op.execute("SET statement_timeout = '120s'")
            try:
                state = op.get_bind().execute(sa.text("""
                    SELECT i.indisvalid, i.indisunique, i.indisprimary,
                           i.indnatts, i.indnkeyatts, i.indpred IS NULL,
                           i.indexprs IS NULL, am.amname,
                           pg_get_indexdef(c.oid, 1, true),
                           pg_get_indexdef(c.oid, 2, true),
                           pg_get_indexdef(c.oid, 3, true)
                    FROM pg_index AS i
                    JOIN pg_class AS c ON c.oid = i.indexrelid
                    JOIN pg_am AS am ON am.oid = c.relam
                    WHERE c.oid = to_regclass(:name)
                      AND i.indrelid = to_regclass('token_usage_logs')
                """), {"name": _INDEX}).one_or_none()
                if state is not None:
                    if not state[0]:
                        op.execute(f"DROP INDEX CONCURRENTLY {_INDEX}")
                    elif tuple(state[1:]) == (
                        False, False, 3, 3, True, True, "btree",
                        "account_id", "event_type", "event_at",
                    ):
                        return  # A previous run committed the index, then lost its revision update.
                    else:
                        raise RuntimeError(f"{_INDEX} exists with an unexpected definition")
                op.create_index(
                    _INDEX, "token_usage_logs", ["account_id", "event_type", "event_at"],
                    postgresql_concurrently=True,
                )
            finally:
                op.execute("RESET statement_timeout")
                op.execute("RESET lock_timeout")
    else:
        op.create_index(_INDEX, "token_usage_logs", ["account_id", "event_type", "event_at"])


def downgrade() -> None:
    if _postgres():
        with op.get_context().autocommit_block():
            op.execute("SET lock_timeout = '5s'")
            op.execute("SET statement_timeout = '120s'")
            try:
                # A prior attempt may have committed the drop before Alembic
                # wrote the older revision. Repeating downgrade must finish.
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
            finally:
                op.execute("RESET statement_timeout")
                op.execute("RESET lock_timeout")
    else:
        op.drop_index(_INDEX, table_name="token_usage_logs")
