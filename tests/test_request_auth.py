"""Unit tests for stage 22.1 bearer extraction from HTTP headers."""

import logging
from unittest.mock import patch

import pytest

import request_auth
import auth.request as auth_request
from exceptions import AuthError


def test_get_bearer_token_from_authorization_header():
    """Bearer token should be extracted from Authorization header."""
    headers = {"authorization": "Bearer vm_st_secret_token"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        assert request_auth.get_bearer_token() == "vm_st_secret_token"


def test_missing_authorization_header_raises_auth_error():
    """Missing Authorization header should fail with explicit auth error."""
    with patch.object(auth_request, "_get_request_headers", return_value={}):
        with pytest.raises(AuthError, match="Missing Authorization"):
            request_auth.get_bearer_token()


def test_missing_authorization_header_emits_security_log(caplog):
    caplog.set_level(logging.WARNING, logger="vetmanager.security")

    with patch.object(auth_request, "_get_request_headers", return_value={}):
        with pytest.raises(AuthError, match="Missing Authorization"):
            request_auth.get_bearer_token()

    records = [
        record for record in caplog.records
        if record.__dict__.get("event_name") == "bearer_auth_failed"
    ]
    assert len(records) == 1
    assert records[0].__dict__.get("source") == "bearer_header"
    assert records[0].__dict__.get("reason") == "missing_authorization"


@pytest.mark.parametrize(
    "header_value",
    [
        "Basic abc",
        "Bearer",
        "Bearer   ",
        "Token abc",
    ],
)
def test_invalid_authorization_header_raises_auth_error(header_value: str):
    """Invalid Authorization forms must not be accepted as bearer auth."""
    headers = {"authorization": header_value}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with pytest.raises(AuthError, match="Invalid Authorization"):
            request_auth.get_bearer_token()


def test_invalid_authorization_header_security_log_does_not_leak_raw_header(caplog):
    caplog.set_level(logging.WARNING, logger="vetmanager.security")
    raw_header = "Basic vm_st_super_secret_token"
    headers = {"authorization": raw_header}

    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with pytest.raises(AuthError, match="Invalid Authorization"):
            request_auth.get_bearer_token()

    records = [
        record for record in caplog.records
        if record.__dict__.get("event_name") == "bearer_auth_failed"
    ]
    assert len(records) == 1
    assert records[0].__dict__.get("source") == "bearer_header"
    assert records[0].__dict__.get("reason") == "invalid_authorization"
    serialized = "\n".join(str(record.__dict__) for record in records)
    assert raw_header not in serialized
    assert "vm_st_super_secret_token" not in serialized
