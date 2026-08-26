"""Describe the authenticated subject of a usage-log row for both channels.

Stage 260. Until now a row could only belong to a service bearer token, so
OAuth traffic had nowhere to be recorded and every activity aggregate answered
for half the users. The row now names the account it belongs to and which of
the two credential kinds produced it.

Revision ID: 20260826_000020
Revises: 20260821_000019
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260826_000020"
down_revision = "20260821_000019"
branch_labels = None
depends_on = None

_SUBJECT_CHECK = "ck_token_usage_logs_single_subject"
_SUBJECT_CONDITION = (
    "(bearer_token_id IS NOT NULL AND oauth_access_token_id IS NULL) "
    "OR (bearer_token_id IS NULL AND oauth_access_token_id IS NOT NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("token_usage_logs") as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("oauth_access_token_id", sa.Integer(), nullable=True))

    # Every existing row is a bearer row, so the account is reachable through
    # the token. Done before the constraint so no row is left ambiguous.
    op.execute(
        "UPDATE token_usage_logs SET account_id = ("
        "SELECT account_id FROM service_bearer_tokens "
        "WHERE service_bearer_tokens.id = token_usage_logs.bearer_token_id) "
        "WHERE account_id IS NULL"
    )

    with op.batch_alter_table("token_usage_logs") as batch_op:
        batch_op.alter_column(
            "bearer_token_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.create_foreign_key(
            "fk_token_usage_logs_account_id",
            "accounts",
            ["account_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_token_usage_logs_oauth_access_token_id",
            "oauth_access_tokens",
            ["oauth_access_token_id"],
            ["id"],
        )
        batch_op.create_check_constraint(_SUBJECT_CHECK, _SUBJECT_CONDITION)


def downgrade() -> None:
    # OAuth rows exist only in the columns being dropped; `bearer_token_id`
    # cannot become NOT NULL while they are there, so the downgrade discards
    # them. This is a real loss of data and is reported, not hidden.
    connection = op.get_bind()
    discarded = connection.execute(
        sa.text("SELECT count(*) FROM token_usage_logs WHERE bearer_token_id IS NULL")
    ).scalar_one()
    if discarded:
        print(f"stage 260 downgrade: discarding {discarded} OAuth usage-log rows")
        connection.execute(
            sa.text("DELETE FROM token_usage_logs WHERE bearer_token_id IS NULL")
        )

    with op.batch_alter_table("token_usage_logs") as batch_op:
        batch_op.drop_constraint(_SUBJECT_CHECK, type_="check")
        batch_op.drop_constraint("fk_token_usage_logs_oauth_access_token_id", type_="foreignkey")
        batch_op.drop_constraint("fk_token_usage_logs_account_id", type_="foreignkey")
        batch_op.alter_column(
            "bearer_token_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.drop_column("oauth_access_token_id")
        batch_op.drop_column("account_id")
