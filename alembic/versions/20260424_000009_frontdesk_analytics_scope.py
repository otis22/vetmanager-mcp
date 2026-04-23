"""Backfill frontdesk preset tokens with analytics.read."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260424_000009"
down_revision = "20260423_000008"
branch_labels = None
depends_on = None


OLD_FRONTDESK_SCOPES = [
    "admissions.read",
    "admissions.write",
    "clients.read",
    "clients.write",
    "finance.read",
    "messaging.write",
    "pets.read",
    "pets.write",
    "reference.read",
    "users.read",
]

NEW_FRONTDESK_SCOPES = [
    "admissions.read",
    "admissions.write",
    "analytics.read",
    "clients.read",
    "clients.write",
    "finance.read",
    "messaging.write",
    "pets.read",
    "pets.write",
    "reference.read",
    "users.read",
]

OLD_FRONTDESK_SCOPES_JSON = json.dumps(OLD_FRONTDESK_SCOPES)
NEW_FRONTDESK_SCOPES_JSON = json.dumps(NEW_FRONTDESK_SCOPES)


def _matches_scope_bundle(raw_value: str | None, expected_scopes: list[str]) -> bool:
    if not raw_value:
        return False
    if isinstance(raw_value, list):
        loaded = raw_value
    else:
        try:
            loaded = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            return False
    if not isinstance(loaded, list) or not all(isinstance(scope, str) for scope in loaded):
        return False
    return sorted(loaded) == sorted(expected_scopes)


def _replace_scope_bundle(expected_scopes: list[str], replacement_json: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, scopes_json FROM service_bearer_tokens")).fetchall()
    for token_id, scopes_json in rows:
        if not _matches_scope_bundle(scopes_json, expected_scopes):
            continue
        bind.execute(
            sa.text("UPDATE service_bearer_tokens SET scopes_json = :scopes_json WHERE id = :token_id"),
            {"scopes_json": replacement_json, "token_id": token_id},
        )


def upgrade() -> None:
    _replace_scope_bundle(OLD_FRONTDESK_SCOPES, NEW_FRONTDESK_SCOPES_JSON)


def downgrade() -> None:
    _replace_scope_bundle(NEW_FRONTDESK_SCOPES, OLD_FRONTDESK_SCOPES_JSON)
