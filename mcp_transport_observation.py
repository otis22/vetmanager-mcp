"""Observe bounded MCP transport rejection classes without changing responses."""

import json

from service_metrics import record_mcp_transport_rejection, record_mcp_transport_response


_MAX_ERROR_BYTES = 4096


def _reason(status: int, body: bytes) -> str:
    # Match the complete upstream message: a client-controlled protocol version
    # can appear inside another 400 message and must not impersonate a reason.
    try:
        payload = json.loads(body)
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else error
    except (ValueError, TypeError):
        message = None
    if status == 404 and message == "Session not found":
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


class MCPTransportObservationMiddleware:
    """Count completed FastMCP 400/404/406 responses via shared metrics."""

    def __init__(self, app, *, path: str = "/mcp") -> None:
        self.app = app
        self.path = path

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return

        status = None
        body = bytearray()

        async def observed_send(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and status in (400, 404, 406):
                if len(body) < _MAX_ERROR_BYTES:
                    body.extend(message.get("body", b"")[:_MAX_ERROR_BYTES - len(body)])
            await send(message)
            if message["type"] == "http.response.start":
                record_mcp_transport_response(route=self.path, method=scope.get("method", ""),
                                              status_code=status)
            if message["type"] == "http.response.body" and status in (400, 404, 406):
                if not message.get("more_body", False):
                    record_mcp_transport_rejection(status_code=status,
                                                   reason=_reason(status, bytes(body)))

        await self.app(scope, receive, observed_send)
