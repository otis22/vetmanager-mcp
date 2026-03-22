"""Regression tests for auth audit sanitization policy."""

from __future__ import annotations

import json

from auth_audit import _serialize_details


def test_serialize_details_redacts_sensitive_top_level_fields():
    payload = json.loads(
        _serialize_details(
            {
                "token_prefix": "vm_st_abcd",
                "api_key": "secret-key",
                "user_token": "user-token-secret",
                "password": "hunter2",
                "authorization": "Bearer vm_st_secret_raw_token",
            }
        )
    )

    assert payload["token_prefix"] == "vm_st_abcd"
    assert payload["api_key"] == "[redacted]"
    assert payload["user_token"] == "[redacted]"
    assert payload["password"] == "[redacted]"
    assert payload["authorization"] == "[redacted]"


def test_serialize_details_redacts_nested_sensitive_fields_and_bearer_patterns():
    payload = json.loads(
        _serialize_details(
            {
                "connection": {
                    "domain": "clinic-a",
                    "api_key": "secret-key",
                    "nested": {
                        "session_cookie": "signed-cookie",
                    },
                },
                "message": "Issued vm_st_secret_raw_token for test flow",
                "items": [
                    {"user_token": "user-token-secret"},
                    "vm_st_second_secret_token",
                ],
            }
        )
    )

    assert payload["connection"]["domain"] == "clinic-a"
    assert payload["connection"]["api_key"] == "[redacted]"
    assert payload["connection"]["nested"]["session_cookie"] == "[redacted]"
    assert payload["message"] == "Issued [redacted] for test flow"
    assert payload["items"][0]["user_token"] == "[redacted]"
    assert payload["items"][1] == "[redacted]"
