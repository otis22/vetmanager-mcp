"""Unit tests for stage 22.1 bearer extraction from HTTP headers."""

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
