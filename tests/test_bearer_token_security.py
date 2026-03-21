"""Unit tests for stage 21.4 bearer token storage helpers."""

import bearer_token_manager
from storage_models import ServiceBearerToken


def test_generate_bearer_token_returns_high_entropy_prefixed_value():
    """Generated bearer token should be opaque and ready for one-time display."""
    token = bearer_token_manager.generate_bearer_token()

    assert token.startswith("vm_st_")
    assert len(token) >= 32


def test_service_bearer_token_stores_only_hash_and_safe_prefix():
    """Model helper must keep only token hash and short prefix for UI/audit."""
    raw_token = bearer_token_manager.generate_bearer_token()
    token = ServiceBearerToken(account_id=1, name="CLI token")

    token.set_raw_token(raw_token)

    assert token.token_hash != raw_token
    assert token.token_prefix != raw_token
    assert raw_token.startswith(token.token_prefix)
    assert len(token.token_prefix) < len(raw_token)
    assert token.verify_raw_token(raw_token) is True


def test_verify_raw_token_rejects_non_matching_secret():
    """Hash verification must fail for a different bearer token."""
    raw_token = bearer_token_manager.generate_bearer_token()
    other_token = bearer_token_manager.generate_bearer_token()
    token = ServiceBearerToken(account_id=1, name="Agent token")
    token.set_raw_token(raw_token)

    assert token.verify_raw_token(other_token) is False
