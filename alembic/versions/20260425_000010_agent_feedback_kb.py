"""Add agent feedback reports and verified known issues."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_000010"
down_revision = "20260424_000009"
branch_labels = None
depends_on = None


FEEDBACK_SOURCES = ("model", "auto", "user_complaint")
FEEDBACK_CATEGORIES = ("bug", "missing_tool", "bad_description", "contract", "perf", "docs", "other")
FEEDBACK_SEVERITIES = ("low", "medium", "high")
FEEDBACK_STATUSES = ("new", "grouped", "triaged", "linked", "ignored")
KNOWN_ISSUE_STATUSES = ("open", "acknowledged", "workaround_available", "fixed", "wontfix")


def _in_constraint(values: tuple[str, ...]) -> str:
    return ", ".join(repr(value) for value in values)


def upgrade() -> None:
    op.create_table(
        "known_issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("related_tool", sa.String(length=128), nullable=True),
        sa.Column("error_fingerprint_hash", sa.String(length=96), nullable=True),
        sa.Column("match_rules_json", sa.Text(), nullable=True),
        sa.Column("agent_playbook_json", sa.Text(), nullable=True),
        sa.Column("public_summary", sa.Text(), nullable=True),
        sa.Column("workaround", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("fixed_in_version", sa.String(length=64), nullable=True),
        sa.Column("report_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"status IN ({_in_constraint(KNOWN_ISSUE_STATUSES)})",
            name="ck_known_issues_status",
        ),
        sa.CheckConstraint(
            f"category IN ({_in_constraint(FEEDBACK_CATEGORIES)})",
            name="ck_known_issues_category",
        ),
        sa.CheckConstraint(
            f"severity IN ({_in_constraint(FEEDBACK_SEVERITIES)})",
            name="ck_known_issues_severity",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_known_issues_related_tool", "known_issues", ["related_tool"])
    op.create_index("ix_known_issues_error_fingerprint_hash", "known_issues", ["error_fingerprint_hash"])
    op.create_index(
        "ix_known_issues_tool_fingerprint",
        "known_issues",
        ["related_tool", "error_fingerprint_hash"],
    )

    op.create_table(
        "agent_feedback_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("bearer_token_id", sa.Integer(), nullable=True),
        sa.Column("related_tool", sa.String(length=128), nullable=True),
        sa.Column("related_call_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("params_shape_json", sa.Text(), nullable=True),
        sa.Column("summary", sa.String(length=240), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column("reproduce", sa.Text(), nullable=True),
        sa.Column("error_fingerprint_hash", sa.String(length=96), nullable=True),
        sa.Column("known_issue_id", sa.Integer(), nullable=True),
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("redaction_version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            f"source IN ({_in_constraint(FEEDBACK_SOURCES)})",
            name="ck_agent_feedback_reports_source",
        ),
        sa.CheckConstraint(
            f"category IN ({_in_constraint(FEEDBACK_CATEGORIES)})",
            name="ck_agent_feedback_reports_category",
        ),
        sa.CheckConstraint(
            f"severity IN ({_in_constraint(FEEDBACK_SEVERITIES)})",
            name="ck_agent_feedback_reports_severity",
        ),
        sa.CheckConstraint(
            f"status IN ({_in_constraint(FEEDBACK_STATUSES)})",
            name="ck_agent_feedback_reports_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["bearer_token_id"], ["service_bearer_tokens.id"]),
        sa.ForeignKeyConstraint(["known_issue_id"], ["known_issues.id"]),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["agent_feedback_reports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_feedback_reports_account_id", "agent_feedback_reports", ["account_id"])
    op.create_index("ix_agent_feedback_reports_bearer_token_id", "agent_feedback_reports", ["bearer_token_id"])
    op.create_index("ix_agent_feedback_reports_related_tool", "agent_feedback_reports", ["related_tool"])
    op.create_index(
        "ix_agent_feedback_reports_error_fingerprint_hash",
        "agent_feedback_reports",
        ["error_fingerprint_hash"],
    )
    op.create_index(
        "ix_agent_feedback_reports_tool_fingerprint",
        "agent_feedback_reports",
        ["related_tool", "error_fingerprint_hash"],
    )
    op.create_index(
        "ix_agent_feedback_reports_status_created",
        "agent_feedback_reports",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_feedback_reports_status_created", table_name="agent_feedback_reports")
    op.drop_index("ix_agent_feedback_reports_tool_fingerprint", table_name="agent_feedback_reports")
    op.drop_index("ix_agent_feedback_reports_error_fingerprint_hash", table_name="agent_feedback_reports")
    op.drop_index("ix_agent_feedback_reports_related_tool", table_name="agent_feedback_reports")
    op.drop_index("ix_agent_feedback_reports_bearer_token_id", table_name="agent_feedback_reports")
    op.drop_index("ix_agent_feedback_reports_account_id", table_name="agent_feedback_reports")
    op.drop_table("agent_feedback_reports")
    op.drop_index("ix_known_issues_tool_fingerprint", table_name="known_issues")
    op.drop_index("ix_known_issues_error_fingerprint_hash", table_name="known_issues")
    op.drop_index("ix_known_issues_related_tool", table_name="known_issues")
    op.drop_table("known_issues")
