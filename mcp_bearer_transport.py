"""Early HTTP rejection of presented invalid MCP bearer credentials."""

import asyncio
from datetime import datetime, timezone
import json
from threading import BoundedSemaphore

from sqlalchemy import select

from bearer_token_manager import hash_bearer_token
from oauth_challenge import build_oauth_bearer_challenge
from oauth_metadata import get_mcp_resource_url
from oauth_service import OAUTH_ACCESS_TOKEN_PREFIX
from storage import get_session_factory
from storage_models import (
    OAUTH_STATUS_ACTIVE, TOKEN_STATUS_DISABLED, OAuthAccessToken, OAuthClient,
    OAuthGrant, ServiceBearerToken,
)


_PREFLIGHT_SLOTS = BoundedSemaphore(16)


def service_token_invalid(token: ServiceBearerToken | None, now: datetime) -> bool:
    return (token is None or token.is_revoked() or token.is_expired(now=now)
            or token.status == TOKEN_STATUS_DISABLED)


def oauth_access_invalid(access: OAuthAccessToken | None, now: datetime) -> bool:
    if access is None or access.status != OAUTH_STATUS_ACTIVE or access.resource != get_mcp_resource_url():
        return True
    expiry = access.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= now


def oauth_grant_client_invalid(grant: OAuthGrant | None, client: OAuthClient | None) -> bool:
    return (grant is None or grant.status != OAUTH_STATUS_ACTIVE
            or client is None or client.status != OAUTH_STATUS_ACTIVE)


async def _is_invalid(raw_token: str) -> bool:
    digest = hash_bearer_token(raw_token)
    now = datetime.now(timezone.utc)
    async with get_session_factory()() as session:
        if raw_token.startswith(OAUTH_ACCESS_TOKEN_PREFIX):
            row = (await session.execute(
                select(OAuthAccessToken, OAuthGrant, OAuthClient)
                .outerjoin(OAuthGrant, OAuthGrant.id == OAuthAccessToken.grant_id)
                .outerjoin(OAuthClient, OAuthClient.client_id == OAuthGrant.client_id)
                .where(OAuthAccessToken.token_hash == digest)
            )).first()
            access, grant, client = row if row is not None else (None, None, None)
            return oauth_access_invalid(access, now) or oauth_grant_client_invalid(grant, client)
        token = await session.scalar(select(ServiceBearerToken).where(ServiceBearerToken.token_hash == digest))
        return service_token_invalid(token, now)


async def _respond(send, status: int, body: dict, challenge: str | None = None) -> None:
    payload = json.dumps(body, separators=(",", ":")).encode()
    headers = [(b"content-type", b"application/json"),
               (b"content-length", str(len(payload)).encode())]
    if challenge is not None:
        headers.append((b"www-authenticate", challenge.encode("ascii")))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


class MCPBearerTransportMiddleware:
    def __init__(self, app, *, path: str = "/mcp") -> None:
        self.app = app
        self.path = path

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return
        authorization_values = [value for name, value in scope.get("headers", ())
                                if name.lower() == b"authorization"]
        if len(authorization_values) > 1:
            await _respond(send, 400, {"error": "invalid_request"})
            return
        authorization = authorization_values[0].strip() if authorization_values else b""
        if not authorization.lower().startswith(b"bearer "):
            await self.app(scope, receive, send)
            return
        token = authorization[7:].strip()
        if not token:
            await self.app(scope, receive, send)
            return
        if len(token) > 512 or any(char < 33 or char > 126 for char in token):
            invalid = True
        elif not _PREFLIGHT_SLOTS.acquire(blocking=False):
            await _respond(send, 503, {"error": "temporarily_unavailable"})
            return
        else:
            try:
                async with asyncio.timeout(0.5):
                    invalid = await _is_invalid(token.decode("ascii"))
            except Exception:
                await _respond(send, 503, {"error": "temporarily_unavailable"})
                return
            finally:
                _PREFLIGHT_SLOTS.release()
        if invalid:
            challenge = build_oauth_bearer_challenge(
                error="invalid_token", error_description="The access token is invalid.")
            await _respond(send, 401, {"error": "invalid_token"}, challenge)
            return
        await self.app(scope, receive, send)
