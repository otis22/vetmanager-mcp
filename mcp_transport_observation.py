"""Observe bounded MCP transport failures and guide stale-session recovery."""

import asyncio
from collections import deque
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
from threading import BoundedSemaphore

from sqlalchemy import select
from starlette.requests import Request

from bearer_token_manager import hash_bearer_token
from oauth_service import OAUTH_ACCESS_TOKEN_PREFIX
from observability_logging import RUNTIME_LOGGER
from request_context import get_request_context
from storage import get_session_factory
from storage_models import Account, OAuthAccessToken, OAuthGrant, ServiceBearerToken

from service_metrics import (
    record_mcp_handshake, record_mcp_session_retry, record_mcp_transport_rejection,
    record_mcp_transport_response,
)


_MAX_ERROR_BYTES = 4096
_MAX_REQUEST_BYTES = 65536
_MAX_REQUEST_CHUNKS = 128
_HANDSHAKE_SLOTS = BoundedSemaphore(16)
_HANDSHAKE_TASKS: set[asyncio.Task] = set()
_VERSION_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SESSION_NOT_FOUND = "Session not found"
_SESSION_GUIDANCE = (
    "Session not found. Close the previous MCP session and send initialize again "
    "without the old Mcp-Session-Id."
)


def _reason(status: int, body: bytes) -> str:
    # Match complete messages: a client-controlled protocol version can appear
    # inside another 400 message and must not impersonate a reason.
    try:
        payload = json.loads(body)
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else error
    except (ValueError, TypeError):
        message = None
    if status == 404 and message in (_SESSION_NOT_FOUND, _SESSION_GUIDANCE):
        return "session_not_found"
    if status == 400:
        if message == "missing_authorization":
            return "missing_auth"
        if message == "Bad Request: Missing session ID":
            return "missing_session"
    if status == 406 and isinstance(message, str) and message.startswith(
            "Not Acceptable: Client must accept"):
        return "invalid_accept"
    return "other"


def _guided_body(body: bytes, headers: list[tuple[bytes, bytes]]) -> bytes | None:
    if any(name.lower() == b"content-encoding" for name, _ in headers):
        return None
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return None
    if payload["error"].get("message") != _SESSION_NOT_FOUND:
        return None
    payload["error"]["message"] = _SESSION_GUIDANCE
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _bearer_digest(scope) -> str | None:
    secret = os.environ.get("WEB_SESSION_SECRET")
    if not secret:
        return None
    for name, value in scope.get("headers", ()):
        if name.lower() != b"authorization":
            continue
        if not value.startswith(b"Bearer ") or not 7 < len(value) <= 519:
            return None
        token = value[7:]
        if not token or any(char < 33 or char > 126 for char in token):
            return None
        return hmac.new(secret.encode(), token, hashlib.sha256).hexdigest()
    return None


def _handshake_request(body: bytes, headers, *, complete: bool, oversized: bool):
    if complete and not body:
        return None
    if oversized:
        return "unknown", "unknown", "body_too_large"
    if not complete:
        return "unknown", "unknown", "body_not_read"
    try:
        payload = json.loads(body)
    except (ValueError, TypeError, RecursionError):
        return "unknown", "unknown", "invalid_request"
    if not isinstance(payload, dict):
        return "unknown", "unknown", "invalid_request"
    method = payload.get("method")
    if method not in ("initialize", "tools/list"):
        return None
    if method == "initialize":
        params = payload.get("params")
        version = params.get("protocolVersion") if isinstance(params, dict) else None
    else:
        version = next((v.decode("ascii", "ignore") for k, v in headers
                        if k.lower() == b"mcp-protocol-version"), None)
    version = version if isinstance(version, str) and _VERSION_RE.fullmatch(version) else "unknown"
    return method, version, None


def _handshake_auth(headers):
    values = [value for name, value in headers if name.lower() == b"authorization"]
    if not values:
        return "none", None
    if len(values) != 1 or not values[0].lower().startswith(b"bearer "):
        return "other", None
    token = values[0][7:].strip()
    if not token or len(token) > 512 or any(c < 33 or c > 126 for c in token):
        return "other", None
    value = token.decode("ascii")
    return ("oauth_access" if value.startswith(OAUTH_ACCESS_TOKEN_PREFIX)
            else "service_bearer"), value


async def _lookup_handshake_account(token: str, source: str) -> int | None:
    digest = hash_bearer_token(token)
    async with get_session_factory()() as session:
        if source == "oauth_access":
            query = (select(OAuthGrant.account_id)
                     .join(OAuthAccessToken, OAuthAccessToken.grant_id == OAuthGrant.id)
                     .join(Account, Account.id == OAuthGrant.account_id)
                     .where(OAuthAccessToken.token_hash == digest))
        else:
            query = (select(ServiceBearerToken.account_id)
                     .join(Account, Account.id == ServiceBearerToken.account_id)
                     .where(ServiceBearerToken.token_hash == digest))
        return await session.scalar(query)


def _handshake_outcome(status: int, response: bytes) -> tuple[str, str]:
    if 200 <= status < 300:
        try:
            text = response.decode("utf-8")
            if text.startswith("event:") or text.startswith("data:"):
                text = next((line[6:] for line in text.splitlines()
                             if line.startswith("data: ")), "")
            payload = json.loads(text)
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                return "rpc_error", "rpc_error"
        except (UnicodeError, ValueError, TypeError):
            pass
        return "success", "none"
    if 400 <= status < 500:
        return "http_4xx", _reason(status, response) if status in (400, 404, 406) else "other"
    if 500 <= status < 600:
        return "http_5xx", "other"
    return "other", "other"


def _emit_handshake(data: dict, *, account_id: int | None, auth_outcome: str) -> None:
    try:
        record_mcp_handshake(method=data["rpc_method"], auth_source=data["auth_source"],
                             auth_outcome=auth_outcome, outcome=data["outcome"])
        RUNTIME_LOGGER.info("MCP handshake observed", extra={
            **data, "account_id": account_id, "auth_outcome": auth_outcome,
            "event_name": "mcp_handshake",
        })
    except Exception:
        pass


def _schedule_handshake(data: dict, token: str | None) -> None:
    if token is None:
        _emit_handshake(data, account_id=None, auth_outcome="absent")
        return
    if not _HANDSHAKE_SLOTS.acquire(blocking=False):
        _emit_handshake(data, account_id=None, auth_outcome="lookup_failed")
        return

    async def observe() -> None:
        try:
            try:
                async with asyncio.timeout(.25):
                    account_id = await _lookup_handshake_account(token, data["auth_source"])
                _emit_handshake(data, account_id=account_id,
                                auth_outcome="matched" if account_id is not None else "unmatched")
            except Exception:
                _emit_handshake(data, account_id=None, auth_outcome="lookup_failed")
        finally:
            _HANDSHAKE_SLOTS.release()

    coroutine = observe()
    try:
        task = asyncio.create_task(coroutine)
    except RuntimeError:
        coroutine.close()
        _HANDSHAKE_SLOTS.release()
        _emit_handshake(data, account_id=None, auth_outcome="lookup_failed")
        return
    _HANDSHAKE_TASKS.add(task)
    task.add_done_callback(_HANDSHAKE_TASKS.discard)


async def wait_handshake_observations() -> None:
    """Wait for in-flight diagnostics in focused tests and shutdown probes."""
    loop = asyncio.get_running_loop()
    while True:
        for task in tuple(_HANDSHAKE_TASKS):
            if task.done() or task.get_loop().is_closed():
                _HANDSHAKE_TASKS.discard(task)
        current = tuple(task for task in _HANDSHAKE_TASKS if task.get_loop() is loop)
        if not current:
            return
        await asyncio.gather(*current, return_exceptions=True)


class MCPTransportObservationMiddleware:
    """Count transport failures; rewrite only the exact stale-session 404."""

    def __init__(self, app, *, path: str = "/mcp") -> None:
        self.app = app
        self.path = path

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return

        handshake = None
        replay = deque()
        if scope.get("method") == "POST":
            captured = bytearray()
            complete = False
            oversized = False
            try:
                async with asyncio.timeout(.25):
                    while not complete and not oversized and len(replay) < _MAX_REQUEST_CHUNKS:
                        part = await receive()
                        replay.append(part)
                        if part["type"] != "http.request":
                            break
                        chunk = part.get("body", b"")
                        if len(captured) + len(chunk) > _MAX_REQUEST_BYTES:
                            oversized = True
                        else:
                            captured.extend(chunk)
                        complete = not part.get("more_body", False)
            except TimeoutError:
                pass
            handshake = _handshake_request(bytes(captured), scope.get("headers", ()),
                                           complete=complete, oversized=oversized)

        async def replay_receive():
            if replay:
                return replay.popleft()
            return await receive()

        status = None
        body = bytearray()
        rpc_body = bytearray()
        pending_start = None
        pending_parts = []
        pending_bytes = 0

        async def send_start(message) -> None:
            await send(message)
            record_mcp_transport_response(route=self.path, method=scope.get("method", ""),
                                          status_code=message["status"])

        async def observed_send(message) -> None:
            nonlocal status, pending_start, pending_bytes
            if message["type"] == "http.response.start":
                status = message["status"]
                if status == 404:
                    pending_start = message
                else:
                    await send_start(message)
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            chunk = message.get("body", b"")
            if handshake is not None and len(rpc_body) < _MAX_ERROR_BYTES:
                rpc_body.extend(chunk[:_MAX_ERROR_BYTES - len(rpc_body)])
            if status in (400, 404, 406) and len(body) < _MAX_ERROR_BYTES:
                body.extend(chunk[:_MAX_ERROR_BYTES - len(body)])
            if pending_start is not None:
                pending_parts.append(message)
                pending_bytes += len(chunk)
                if pending_bytes > _MAX_ERROR_BYTES:
                    await send_start(pending_start)
                    pending_start = None
                    for part in pending_parts:
                        await send(part)
                    pending_parts.clear()
                    pending_bytes = 0
                elif not message.get("more_body", False):
                    original = b"".join(part.get("body", b"") for part in pending_parts)
                    headers = pending_start.get("headers", [])
                    guided = _guided_body(original, headers)
                    if guided is not None:
                        revised_headers = [
                            (name, str(len(guided)).encode() if name.lower() == b"content-length" else value)
                            for name, value in headers
                        ]
                        await send_start({**pending_start, "headers": revised_headers})
                        await send({"type": "http.response.body", "body": guided})
                    else:
                        await send_start(pending_start)
                        for part in pending_parts:
                            await send(part)
                    pending_start = None
                    pending_parts.clear()
                    pending_bytes = 0
            else:
                await send(message)
            if status in (400, 404, 406) and not message.get("more_body", False):
                reason = _reason(status, bytes(body))
                record_mcp_transport_rejection(status_code=status, reason=reason)
                if status == 404 and reason == "session_not_found":
                    digest = _bearer_digest(scope)
                    if digest:
                        record_mcp_session_retry(digest)

        await self.app(scope, replay_receive, observed_send)
        if handshake is not None and status is not None:
            rpc_method, protocol_version, request_reason = handshake
            outcome, reason = _handshake_outcome(status, bytes(rpc_body))
            auth_source, token = _handshake_auth(scope.get("headers", ()))
            context = get_request_context(Request(scope))
            _schedule_handshake({
                "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "rpc_method": rpc_method, "http_method": "POST", "channel": "mcp_http",
                "auth_source": auth_source, "protocol_version": protocol_version,
                "http_status": status, "outcome": outcome,
                "reason": request_reason if rpc_method == "unknown" else reason,
                "request_id": context["request_id"],
            }, token)
