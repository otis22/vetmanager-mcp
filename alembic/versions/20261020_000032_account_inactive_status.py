"""Allow an explicit inactive account status without changing existing rows."""

from alembic import op
from sqlalchemy import text

revision = "20261020_000032"
down_revision = "20261017_000031"
branch_labels = None
depends_on = None


def _require_safe_sqlite_batch() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and bind.execute(text("PRAGMA foreign_keys")).scalar_one():
        raise RuntimeError("SQLite foreign_keys must be OFF for accounts table rebuild")


def upgrade() -> None:
    _require_safe_sqlite_batch()
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("ck_accounts_status", type_="check")
        batch.create_check_constraint(
            "ck_accounts_status", "status IN ('active', 'inactive')"
        )


def downgrade() -> None:
    _require_safe_sqlite_batch()
    inactive_count = op.get_bind().execute(
        text("SELECT count(*) FROM accounts WHERE status != 'active'")
    ).scalar_one()
    if inactive_count:
        raise RuntimeError("Cannot downgrade while inactive accounts exist")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("ck_accounts_status", type_="check")
        batch.create_check_constraint("ck_accounts_status", "status IN ('active')")
