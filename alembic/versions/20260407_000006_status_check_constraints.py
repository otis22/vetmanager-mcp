"""Add CHECK constraints for status columns on accounts, connections, and tokens."""

from alembic import op
from sqlalchemy import text


revision = "20260407_000006"
down_revision = "20260401_000005"
branch_labels = None
depends_on = None


# Use batch mode for SQLite compatibility (ALTER TABLE ADD CONSTRAINT
# is not supported by older SQLite versions).


def upgrade() -> None:
    # Normalize any existing rows with unexpected status values to safe defaults
    # before adding CHECK constraints, otherwise the migration would fail on
    # production data with legacy values.
    bind = op.get_bind()
    # Note: NOT IN excludes NULL by SQL semantics, so we explicitly cover NULL too
    # even though all status columns are declared NOT NULL.
    bind.execute(text(
        "UPDATE accounts SET status = 'active' "
        "WHERE status IS NULL OR status NOT IN ('active')"
    ))
    bind.execute(text(
        "UPDATE vetmanager_connections SET status = 'disabled' "
        "WHERE status IS NULL OR status NOT IN ('active', 'disabled')"
    ))
    bind.execute(text(
        "UPDATE service_bearer_tokens SET status = 'disabled' "
        "WHERE status IS NULL OR status NOT IN ('active', 'revoked', 'expired', 'disabled')"
    ))

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.create_check_constraint(
            "ck_accounts_status",
            "status IN ('active')",
        )

    with op.batch_alter_table("vetmanager_connections") as batch_op:
        batch_op.create_check_constraint(
            "ck_vetmanager_connections_status",
            "status IN ('active', 'disabled')",
        )

    with op.batch_alter_table("service_bearer_tokens") as batch_op:
        batch_op.create_check_constraint(
            "ck_service_bearer_tokens_status",
            "status IN ('active', 'revoked', 'expired', 'disabled')",
        )


def downgrade() -> None:
    with op.batch_alter_table("service_bearer_tokens") as batch_op:
        batch_op.drop_constraint("ck_service_bearer_tokens_status", type_="check")

    with op.batch_alter_table("vetmanager_connections") as batch_op:
        batch_op.drop_constraint("ck_vetmanager_connections_status", type_="check")

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_constraint("ck_accounts_status", type_="check")
