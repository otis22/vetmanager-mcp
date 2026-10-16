"""Observe bounded MCP transport failures and guide stale-session recovery."""

import hashlib
import hmac
import json
import os

from service_metrics import (
    record_mcp_session_retry, record_mcp_transport_rejection,
    record_mcp_transport_response,
)


_MAX_ERROR_BYTES = 4096
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


class MCPTransportObservationMiddleware:
    """Count transport failures; rewrite only the exact stale-session 404."""

    def __init__(self, app, *, path: str = "/mcp") -> None:
        self.app = app
        self.path = path

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return

        status = None
        body = bytearray()
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

        await self.app(scope, receive, observed_send)
