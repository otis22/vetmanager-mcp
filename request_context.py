"""Request/correlation id helpers shared by web responses and logging."""

from __future__ import annotations

from secrets import token_hex

from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"
_REQUEST_ID_STATE_KEY = "_request_id"
_CORRELATION_ID_STATE_KEY = "_correlation_id"


def _normalize_header_value(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _ensure_request_state(request: Request, *, key: str, value_factory) -> str:
    existing = getattr(request.state, key, None)
    if existing:
        return existing
    value = value_factory()
    setattr(request.state, key, value)
    return value


def get_request_context(request: Request) -> dict[str, str]:
    """Return stable request and correlation ids for one HTTP request."""
    request_id = _ensure_request_state(
        request,
        key=_REQUEST_ID_STATE_KEY,
        value_factory=lambda: _normalize_header_value(request.headers.get(REQUEST_ID_HEADER)) or token_hex(8),
    )
    correlation_id = _ensure_request_state(
        request,
        key=_CORRELATION_ID_STATE_KEY,
        value_factory=lambda: (
            _normalize_header_value(request.headers.get(CORRELATION_ID_HEADER))
            or _normalize_header_value(request.headers.get(REQUEST_ID_HEADER))
            or request_id
        ),
    )
    return {
        "request_id": request_id,
        "correlation_id": correlation_id,
    }


def get_current_request_context() -> dict[str, str]:
    """Return current FastMCP HTTP request context when available."""
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
    except Exception:
        return {}
    return get_request_context(request)


def attach_request_context_headers(response: Response, request: Request) -> None:
    """Expose request ids on outgoing web responses."""
    context = get_request_context(request)
    response.headers[REQUEST_ID_HEADER] = context["request_id"]
    response.headers[CORRELATION_ID_HEADER] = context["correlation_id"]
