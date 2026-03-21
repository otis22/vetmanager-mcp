"""Unit tests for stage 21.5 bearer token lifecycle helpers."""

from datetime import datetime, timedelta, timezone

from storage_models import ServiceBearerToken


def test_revoke_marks_token_revoked_and_inactive():
    """Revoking token should set timestamp, status and deactivate it."""
    token = ServiceBearerToken(
        account_id=1,
        name="CLI",
        token_prefix="vm_st_demo",
        token_hash="hash",
        status="active",
    )

    token.revoke()

    assert token.status == "revoked"
    assert token.revoked_at is not None
    assert token.is_active() is False


def test_sync_status_marks_expired_token_inactive():
    """Expired token should move to expired state when evaluated."""
    token = ServiceBearerToken(
        account_id=1,
        name="CLI",
        token_prefix="vm_st_demo",
        token_hash="hash",
        status="active",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    assert token.is_active() is False
    assert token.status == "expired"


def test_mark_used_updates_last_used_at_for_active_token():
    """mark_used should stamp last_used_at for later accounting."""
    token = ServiceBearerToken(
        account_id=1,
        name="CLI",
        token_prefix="vm_st_demo",
        token_hash="hash",
        status="active",
    )

    token.mark_used()

    assert token.last_used_at is not None
    assert token.status == "active"
