"""OAuth v1 service helpers for ChatGPT public-client linking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
from secrets import token_urlsafe
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bearer_token_manager import build_token_prefix, hash_bearer_token
from oauth_metadata import get_mcp_resource_url
from storage_models import (
    OAUTH_STATUS_ACTIVE,
    OAUTH_STATUS_REVOKED,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
)
from token_scopes import LEGACY_FULL_ACCESS_SCOPE_SNAPSHOTS, SUPPORTED_TOKEN_SCOPES, normalize_token_scopes
from tool_access_registry import (
    PRESET_FRONTDESK,
    PRESET_FULL_ACCESS,
    PRESET_READ_ONLY,
    PRESET_REPORT_AI,
    TOKEN_PRESET_SCOPES,
    infer_token_preset,
)
from web_auth import get_web_session_secret

OAUTH_CLIENT_ID_PREFIX = "vm_oc_"
OAUTH_AUTH_CODE_PREFIX = "vm_oac_"
OAUTH_ACCESS_TOKEN_PREFIX = "vm_oat_"
OAUTH_REFRESH_TOKEN_PREFIX = "vm_ort_"
OAUTH_CLIENT_ID_BYTES = 24
OAUTH_AUTH_CODE_BYTES = 32
OAUTH_ACCESS_TOKEN_BYTES = 32
OAUTH_REFRESH_TOKEN_BYTES = 32
OAUTH_DCR_MAX_BODY_BYTES = 32 * 1024
OAUTH_DCR_DUPLICATE_WINDOW_SECONDS = 60 * 60
OAUTH_DCR_DUPLICATE_LIMIT = 50
OAUTH_AUTHORIZE_STATE_TTL_SECONDS = 10 * 60
OAUTH_AUTH_CODE_TTL_SECONDS = 10 * 60
OAUTH_ACCESS_TOKEN_TTL_SECONDS = 60 * 60
OAUTH_REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
OAUTH_DCR_GRANT_TYPES = ("authorization_code", "refresh_token")
OAUTH_DCR_RESPONSE_TYPES = ("code",)
OAUTH_DCR_TOKEN_ENDPOINT_AUTH_METHOD = "none"
CHATGPT_OAUTH_ACCESS_PRESETS = (
    PRESET_READ_ONLY,
    PRESET_REPORT_AI,
    PRESET_FRONTDESK,
    PRESET_FULL_ACCESS,
)
PKCE_VERIFIER_ALLOWED_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "-._~"
)


class OAuthRequestError(Exception):
    """OAuth/DCR request error safe to expose as JSON."""

    def __init__(self, error: str, description: str, *, status_code: int = 400):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


def _stable_json(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=True, separators=(",", ":"))


def _scope_string(scopes: tuple[str, ...] | list[str]) -> str:
    return " ".join(normalize_token_scopes(scopes))


def _is_full_access_scope(scope: str) -> bool:
    return is_broad_oauth_full_access_scope(scope.split())


def is_broad_oauth_full_access_scope(scopes: tuple[str, ...] | list[str]) -> bool:
    normalized = tuple(normalize_token_scopes(scopes))
    if normalized == TOKEN_PRESET_SCOPES[PRESET_FULL_ACCESS]:
        return True
    normalized_set = set(normalized)
    return any(set(snapshot).issubset(normalized_set) for snapshot in LEGACY_FULL_ACCESS_SCOPE_SNAPSHOTS)


def narrow_oauth_authorize_request_scope(
    request_data: dict,
    *,
    access_preset: str,
    confirm_full_access: bool,
) -> dict:
    """Apply the account owner's selected access preset to an OAuth authorize request."""
    selected_preset = (access_preset or "").strip()
    if not selected_preset:
        raise OAuthRequestError("invalid_request", "access_preset is required.")
    if selected_preset not in CHATGPT_OAUTH_ACCESS_PRESETS:
        raise OAuthRequestError("invalid_request", "Unsupported access preset.")
    if selected_preset == PRESET_FULL_ACCESS and not confirm_full_access:
        raise OAuthRequestError("invalid_request", "Full access requires explicit confirmation.")

    requested_scopes = tuple(normalize_token_scopes(list(request_data.get("scopes") or [])))
    preset_scopes = set(TOKEN_PRESET_SCOPES[selected_preset])
    final_scopes = tuple(scope for scope in requested_scopes if scope in preset_scopes)
    if not final_scopes:
        raise OAuthRequestError(
            "invalid_scope",
            "Selected access level does not include any requested scopes. Choose another access level or reconnect ChatGPT.",
        )

    narrowed = dict(request_data)
    narrowed["scopes"] = list(final_scopes)
    narrowed["scope"] = _scope_string(list(final_scopes))
    narrowed["access_preset"] = selected_preset
    return narrowed


def _b64url_encode(raw_value: bytes) -> str:
    return base64.urlsafe_b64encode(raw_value).decode("ascii").rstrip("=")


def _b64url_decode(raw_value: str) -> bytes:
    padding = "=" * (-len(raw_value) % 4)
    return base64.urlsafe_b64decode((raw_value + padding).encode("ascii"))


def _sign_payload(payload: str) -> str:
    return hmac.new(
        get_web_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _pkce_s256_challenge(code_verifier: str) -> str:
    return _b64url_encode(hashlib.sha256(code_verifier.encode("ascii")).digest())


def _validate_pkce_verifier(code_verifier: str) -> None:
    if not 43 <= len(code_verifier) <= 128:
        raise OAuthRequestError("invalid_grant", "PKCE verifier is invalid.")
    if any(char not in PKCE_VERIFIER_ALLOWED_CHARS for char in code_verifier):
        raise OAuthRequestError("invalid_grant", "PKCE verifier is invalid.")


def _generate_oauth_access_token() -> str:
    return f"{OAUTH_ACCESS_TOKEN_PREFIX}{token_urlsafe(OAUTH_ACCESS_TOKEN_BYTES)}"


def _generate_oauth_refresh_token() -> str:
    return f"{OAUTH_REFRESH_TOKEN_PREFIX}{token_urlsafe(OAUTH_REFRESH_TOKEN_BYTES)}"


def _require_string_list(value, *, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OAuthRequestError("invalid_client_metadata", f"{field_name} must be a string array.")
    return [item.strip() for item in value if item.strip()]


def _validate_redirect_uris(payload: dict) -> list[str]:
    values = _require_string_list(payload.get("redirect_uris"), field_name="redirect_uris")
    if not values:
        raise OAuthRequestError("invalid_redirect_uri", "redirect_uris must contain at least one URI.")
    for uri in values:
        parsed = urlparse(uri)
        if parsed.scheme != "https" or not parsed.netloc:
            raise OAuthRequestError("invalid_redirect_uri", "redirect_uris must use HTTPS.")
        if parsed.fragment:
            raise OAuthRequestError("invalid_redirect_uri", "redirect_uris must not include fragments.")
    return values


def _validate_optional_string_list(
    payload: dict,
    *,
    field_name: str,
    default: tuple[str, ...],
    allowed: tuple[str, ...],
) -> list[str]:
    if field_name not in payload:
        return list(default)
    values = _require_string_list(payload.get(field_name), field_name=field_name)
    if not values or any(value not in allowed for value in values):
        raise OAuthRequestError("invalid_client_metadata", f"Unsupported {field_name}.")
    return values


def _validate_scope(payload: dict) -> str:
    raw_scope = payload.get("scope")
    if raw_scope is None:
        return " ".join(SUPPORTED_TOKEN_SCOPES)
    if not isinstance(raw_scope, str):
        raise OAuthRequestError("invalid_client_metadata", "scope must be a string.")
    try:
        scopes = normalize_token_scopes(raw_scope.split())
    except ValueError as exc:
        raise OAuthRequestError("invalid_scope", str(exc)) from exc
    if not scopes:
        raise OAuthRequestError("invalid_scope", "scope must contain at least one supported scope.")
    return " ".join(scopes)


async def register_oauth_client(session: AsyncSession, payload: dict) -> dict:
    """Validate DCR metadata and persist a public OAuth client."""
    if not isinstance(payload, dict):
        raise OAuthRequestError("invalid_client_metadata", "JSON object expected.")

    redirect_uris = _validate_redirect_uris(payload)
    token_endpoint_auth_method = payload.get(
        "token_endpoint_auth_method",
        OAUTH_DCR_TOKEN_ENDPOINT_AUTH_METHOD,
    )
    if token_endpoint_auth_method != OAUTH_DCR_TOKEN_ENDPOINT_AUTH_METHOD:
        raise OAuthRequestError(
            "invalid_client_metadata",
            "Only public clients with token_endpoint_auth_method=none are supported.",
        )
    grant_types = _validate_optional_string_list(
        payload,
        field_name="grant_types",
        default=OAUTH_DCR_GRANT_TYPES,
        allowed=OAUTH_DCR_GRANT_TYPES,
    )
    response_types = _validate_optional_string_list(
        payload,
        field_name="response_types",
        default=OAUTH_DCR_RESPONSE_TYPES,
        allowed=OAUTH_DCR_RESPONSE_TYPES,
    )
    client_name = payload.get("client_name")
    if client_name is not None and not isinstance(client_name, str):
        raise OAuthRequestError("invalid_client_metadata", "client_name must be a string.")
    client_name = (client_name or "ChatGPT").strip()[:240] or "ChatGPT"
    scope = _validate_scope(payload)

    redirect_uris_json = _stable_json(redirect_uris)
    grant_types_json = _stable_json(grant_types)
    response_types_json = _stable_json(response_types)
    window_start = datetime.now(timezone.utc) - timedelta(seconds=OAUTH_DCR_DUPLICATE_WINDOW_SECONDS)
    duplicate_count = await session.scalar(
        select(func.count())
        .select_from(OAuthClient)
        .where(
            OAuthClient.status == OAUTH_STATUS_ACTIVE,
            OAuthClient.client_name == client_name,
            OAuthClient.redirect_uris_json == redirect_uris_json,
            OAuthClient.created_at >= window_start,
        )
    )
    if int(duplicate_count or 0) >= OAUTH_DCR_DUPLICATE_LIMIT:
        raise OAuthRequestError(
            "temporarily_unavailable",
            "Too many equivalent client registrations.",
            status_code=429,
        )

    client = OAuthClient(
        client_id=f"{OAUTH_CLIENT_ID_PREFIX}{token_urlsafe(OAUTH_CLIENT_ID_BYTES)}",
        client_name=client_name,
        redirect_uris_json=redirect_uris_json,
        token_endpoint_auth_method=token_endpoint_auth_method,
        grant_types_json=grant_types_json,
        response_types_json=response_types_json,
        scope=scope,
        status=OAUTH_STATUS_ACTIVE,
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)

    issued_at = client.created_at
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    return {
        "client_id": client.client_id,
        "client_id_issued_at": int(issued_at.timestamp()),
        "client_name": client.client_name,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "grant_types": grant_types,
        "response_types": response_types,
        "scope": scope,
    }


async def validate_oauth_authorize_request(session: AsyncSession, params) -> dict:
    """Validate OAuth authorize params and return signed request data."""
    response_type = (params.get("response_type") or "").strip()
    if response_type != "code":
        raise OAuthRequestError("unsupported_response_type", "response_type must be code.")
    client_id = (params.get("client_id") or "").strip()
    client = await session.scalar(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.status == OAUTH_STATUS_ACTIVE,
        )
    )
    if client is None:
        raise OAuthRequestError("invalid_client", "Unknown OAuth client.")

    redirect_uri = (params.get("redirect_uri") or "").strip()
    registered_redirect_uris = json.loads(client.redirect_uris_json)
    if redirect_uri not in registered_redirect_uris:
        raise OAuthRequestError("invalid_request", "redirect_uri is not registered for this client.")

    resource = (params.get("resource") or "").strip()
    if resource != get_mcp_resource_url():
        raise OAuthRequestError("invalid_target", "resource must match the MCP resource.")

    code_challenge = (params.get("code_challenge") or "").strip()
    if not code_challenge:
        raise OAuthRequestError("invalid_request", "code_challenge is required.")
    if (params.get("code_challenge_method") or "").strip() != "S256":
        raise OAuthRequestError("invalid_request", "code_challenge_method must be S256.")

    requested_scope = (params.get("scope") or client.scope).strip()
    try:
        requested_scopes = normalize_token_scopes(requested_scope.split())
    except ValueError as exc:
        raise OAuthRequestError("invalid_scope", str(exc)) from exc
    client_scopes = set(normalize_token_scopes(client.scope.split()))
    if not requested_scopes or any(scope not in client_scopes for scope in requested_scopes):
        raise OAuthRequestError("invalid_scope", "Requested scope is not allowed for this client.")

    return {
        "client_id": client.client_id,
        "client_name": client.client_name or "ChatGPT",
        "redirect_uri": redirect_uri,
        "resource": resource,
        "scope": " ".join(requested_scopes),
        "scopes": requested_scopes,
        "state": (params.get("state") or "").strip(),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }


async def _require_active_oauth_client(session: AsyncSession, client_id: str) -> OAuthClient:
    client = await session.scalar(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.status == OAUTH_STATUS_ACTIVE,
        )
    )
    if client is None:
        raise OAuthRequestError("invalid_client", "OAuth client is not active.")
    return client


def sign_oauth_authorize_request(data: dict, *, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    payload = dict(data)
    payload["iat"] = int(current.timestamp())
    encoded_payload = _b64url_encode(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    )
    return f"{encoded_payload}.{_sign_payload(encoded_payload)}"


def read_oauth_authorize_request(raw_state: str, *, now: datetime | None = None) -> dict:
    try:
        encoded_payload, signature = raw_state.split(".", 1)
    except ValueError as exc:
        raise OAuthRequestError("invalid_request", "Invalid authorization request state.") from exc
    if not hmac.compare_digest(signature, _sign_payload(encoded_payload)):
        raise OAuthRequestError("invalid_request", "Invalid authorization request state.")
    try:
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        raise OAuthRequestError("invalid_request", "Invalid authorization request state.") from exc
    try:
        issued_at = datetime.fromtimestamp(int(payload.get("iat", 0)), tz=timezone.utc)
    except (TypeError, ValueError, OSError) as exc:
        raise OAuthRequestError("invalid_request", "Invalid authorization request state.") from exc
    current = now or datetime.now(timezone.utc)
    if current - issued_at > timedelta(seconds=OAUTH_AUTHORIZE_STATE_TTL_SECONDS):
        raise OAuthRequestError("invalid_request", "Authorization request state expired.")
    return payload


async def create_oauth_authorization_code(
    session: AsyncSession,
    request_data: dict,
    *,
    account_id: int,
    vetmanager_connection_id: int,
) -> str:
    raw_code = f"{OAUTH_AUTH_CODE_PREFIX}{token_urlsafe(OAUTH_AUTH_CODE_BYTES)}"
    code = OAuthAuthorizationCode(
        code_prefix=build_token_prefix(raw_code),
        code_hash=hash_bearer_token(raw_code),
        client_id=request_data["client_id"],
        redirect_uri=request_data["redirect_uri"],
        resource=request_data["resource"],
        scope=request_data["scope"],
        access_preset=request_data.get("access_preset"),
        code_challenge=request_data["code_challenge"],
        code_challenge_method=request_data["code_challenge_method"],
        account_id=account_id,
        vetmanager_connection_id=vetmanager_connection_id,
        status=OAUTH_STATUS_ACTIVE,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=OAUTH_AUTH_CODE_TTL_SECONDS),
    )
    session.add(code)
    await session.commit()
    return raw_code


def build_authorization_redirect_uri(redirect_uri: str, *, code: str, state: str) -> str:
    parsed = urlparse(redirect_uri)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items.append(("code", code))
    if state:
        query_items.append(("state", state))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


async def _issue_oauth_token_pair(
    session: AsyncSession,
    *,
    grant_id: int,
    scope: str,
    resource: str,
) -> dict:
    now = datetime.now(timezone.utc)
    raw_access_token = _generate_oauth_access_token()
    raw_refresh_token = _generate_oauth_refresh_token()
    access_token = OAuthAccessToken(
        grant_id=grant_id,
        token_prefix=build_token_prefix(raw_access_token),
        token_hash=hash_bearer_token(raw_access_token),
        scope=scope,
        resource=resource,
        status=OAUTH_STATUS_ACTIVE,
        expires_at=now + timedelta(seconds=OAUTH_ACCESS_TOKEN_TTL_SECONDS),
    )
    refresh_token = OAuthRefreshToken(
        grant_id=grant_id,
        token_prefix=build_token_prefix(raw_refresh_token),
        token_hash=hash_bearer_token(raw_refresh_token),
        scope=scope,
        resource=resource,
        status=OAUTH_STATUS_ACTIVE,
        expires_at=now + timedelta(seconds=OAUTH_REFRESH_TOKEN_TTL_SECONDS),
    )
    session.add_all([access_token, refresh_token])
    await session.flush()
    return {
        "access_token": raw_access_token,
        "token_type": "Bearer",
        "expires_in": OAUTH_ACCESS_TOKEN_TTL_SECONDS,
        "refresh_token": raw_refresh_token,
        "scope": scope,
    }


async def exchange_oauth_authorization_code(session: AsyncSession, form: dict[str, str]) -> dict:
    """Exchange a single-use authorization code for access + refresh tokens."""
    raw_code = (form.get("code") or "").strip()
    client_id = (form.get("client_id") or "").strip()
    redirect_uri = (form.get("redirect_uri") or "").strip()
    resource = (form.get("resource") or "").strip()
    code_verifier = (form.get("code_verifier") or "").strip()
    if not raw_code or not client_id or not redirect_uri or not resource or not code_verifier:
        raise OAuthRequestError("invalid_request", "code, client_id, redirect_uri, resource and code_verifier are required.")

    code = await session.scalar(
        select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code_hash == hash_bearer_token(raw_code))
    )
    now = datetime.now(timezone.utc)
    if code is None or code.status != OAUTH_STATUS_ACTIVE or code.consumed_at is not None:
        raise OAuthRequestError("invalid_grant", "Authorization code is invalid.")
    expires_at = code.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise OAuthRequestError("invalid_grant", "Authorization code is expired.")
    if code.client_id != client_id or code.redirect_uri != redirect_uri or code.resource != resource:
        raise OAuthRequestError("invalid_grant", "Authorization code binding mismatch.")
    await _require_active_oauth_client(session, code.client_id)
    _validate_pkce_verifier(code_verifier)
    if not hmac.compare_digest(_pkce_s256_challenge(code_verifier), code.code_challenge):
        raise OAuthRequestError("invalid_grant", "PKCE verification failed.")

    result = await session.execute(
        update(OAuthAuthorizationCode)
        .where(
            OAuthAuthorizationCode.id == code.id,
            OAuthAuthorizationCode.status == OAUTH_STATUS_ACTIVE,
            OAuthAuthorizationCode.consumed_at.is_(None),
        )
        .values(status="consumed", consumed_at=now)
    )
    if result.rowcount != 1:
        await session.rollback()
        raise OAuthRequestError("invalid_grant", "Authorization code is invalid.")

    grant = OAuthGrant(
        account_id=code.account_id,
        vetmanager_connection_id=code.vetmanager_connection_id,
        client_id=code.client_id,
        scopes_json=json.dumps(code.scope.split(), ensure_ascii=True),
        access_preset=code.access_preset or infer_token_preset(tuple(normalize_token_scopes(code.scope.split()))),
        status=OAUTH_STATUS_ACTIVE,
    )
    session.add(grant)
    await session.flush()
    token_payload = await _issue_oauth_token_pair(
        session,
        grant_id=grant.id,
        scope=code.scope,
        resource=code.resource,
    )
    await session.commit()
    return token_payload


async def _revoke_grant_family(session: AsyncSession, grant_id: int, *, reason: str) -> None:
    now = datetime.now(timezone.utc)
    await session.execute(
        update(OAuthGrant)
        .where(OAuthGrant.id == grant_id)
        .values(status=OAUTH_STATUS_REVOKED, revoked_at=now, revocation_reason=reason)
    )
    await session.execute(
        update(OAuthAccessToken)
        .where(OAuthAccessToken.grant_id == grant_id)
        .values(status=OAUTH_STATUS_REVOKED, revoked_at=now)
    )
    await session.execute(
        update(OAuthRefreshToken)
        .where(OAuthRefreshToken.grant_id == grant_id)
        .values(status=OAUTH_STATUS_REVOKED, revoked_at=now)
    )


async def revoke_oauth_grant_family(
    session: AsyncSession,
    *,
    account_id: int,
    grant_id: int,
    reason: str = "account_disconnect",
) -> None:
    grant = await session.get(OAuthGrant, grant_id)
    if grant is None or grant.account_id != account_id:
        raise ValueError("OAuth grant not found.")
    await _revoke_grant_family(session, grant.id, reason=reason)
    await session.commit()


async def exchange_oauth_refresh_token(session: AsyncSession, form: dict[str, str]) -> dict:
    """Rotate a refresh token and return a new token pair."""
    raw_refresh_token = (form.get("refresh_token") or "").strip()
    client_id = (form.get("client_id") or "").strip()
    resource = (form.get("resource") or "").strip()
    if not raw_refresh_token or not client_id or not resource:
        raise OAuthRequestError("invalid_request", "refresh_token, client_id and resource are required.")

    refresh_token = await session.scalar(
        select(OAuthRefreshToken).where(OAuthRefreshToken.token_hash == hash_bearer_token(raw_refresh_token))
    )
    now = datetime.now(timezone.utc)
    if refresh_token is None:
        raise OAuthRequestError("invalid_grant", "Refresh token is invalid.")
    grant = await session.get(OAuthGrant, refresh_token.grant_id)
    if grant is None or grant.client_id != client_id or refresh_token.resource != resource:
        raise OAuthRequestError("invalid_grant", "Refresh token binding mismatch.")
    await _require_active_oauth_client(session, grant.client_id)
    if grant.status != OAUTH_STATUS_ACTIVE:
        raise OAuthRequestError("invalid_grant", "Grant is not active.")
    if grant.access_preset is None and _is_full_access_scope(refresh_token.scope):
        await _revoke_grant_family(session, grant.id, reason="legacy_full_access_relink_required")
        await session.commit()
        raise OAuthRequestError(
            "invalid_grant",
            "This ChatGPT connection used legacy full access. Reconnect ChatGPT and choose an access level.",
        )
    expires_at = refresh_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        await _revoke_grant_family(session, grant.id, reason="refresh_expired")
        await session.commit()
        raise OAuthRequestError("invalid_grant", "Refresh token is expired.")
    if refresh_token.status != OAUTH_STATUS_ACTIVE or refresh_token.used_at is not None:
        await _revoke_grant_family(session, grant.id, reason="refresh_reuse")
        await session.commit()
        raise OAuthRequestError("invalid_grant", "Refresh token reuse detected.")

    result = await session.execute(
        update(OAuthRefreshToken)
        .where(
            OAuthRefreshToken.id == refresh_token.id,
            OAuthRefreshToken.status == OAUTH_STATUS_ACTIVE,
            OAuthRefreshToken.used_at.is_(None),
        )
        .values(status=OAUTH_STATUS_REVOKED, used_at=now, revoked_at=now)
    )
    if result.rowcount != 1:
        await _revoke_grant_family(session, grant.id, reason="refresh_race")
        await session.commit()
        raise OAuthRequestError("invalid_grant", "Refresh token reuse detected.")

    token_payload = await _issue_oauth_token_pair(
        session,
        grant_id=grant.id,
        scope=refresh_token.scope,
        resource=refresh_token.resource,
    )
    new_refresh_token = await session.scalar(
        select(OAuthRefreshToken).where(
            OAuthRefreshToken.token_hash == hash_bearer_token(token_payload["refresh_token"])
        )
    )
    if new_refresh_token is not None:
        refresh_token.replaced_by_token_id = new_refresh_token.id
    await session.commit()
    return token_payload


async def exchange_oauth_token(session: AsyncSession, form: dict[str, str]) -> dict:
    grant_type = (form.get("grant_type") or "").strip()
    if grant_type == "authorization_code":
        return await exchange_oauth_authorization_code(session, form)
    if grant_type == "refresh_token":
        return await exchange_oauth_refresh_token(session, form)
    raise OAuthRequestError("unsupported_grant_type", "Unsupported grant_type.")
