"""Helpers for secure bearer token generation and verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_PREFIX_LENGTH = 12
TOKEN_URLSAFE_BYTES = 32
TOKEN_PREFIX_LABEL = "vm_st_"


def generate_bearer_token() -> str:
    """Return a new high-entropy bearer token for one-time display."""
    return f"{TOKEN_PREFIX_LABEL}{secrets.token_urlsafe(TOKEN_URLSAFE_BYTES)}"


def build_token_prefix(raw_token: str) -> str:
    """Return safe short token prefix for UI and audit display."""
    return raw_token[:TOKEN_PREFIX_LENGTH]


def hash_bearer_token(raw_token: str) -> str:
    """Return deterministic SHA-256 hash of the raw bearer token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def verify_bearer_token(raw_token: str, token_hash: str) -> bool:
    """Constant-time verification of raw bearer token against stored hash."""
    return hmac.compare_digest(hash_bearer_token(raw_token), token_hash)
