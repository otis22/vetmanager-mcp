"""Contract tests for request/correlation id helpers."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from request_context import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    attach_request_context_headers,
    get_request_context,
)


def _make_request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_get_request_context_generates_ids_when_headers_missing():
    request = _make_request()

    context = get_request_context(request)

    assert context["request_id"]
    assert context["correlation_id"] == context["request_id"]


def test_get_request_context_uses_header_values_when_present():
    request = _make_request(
        headers=[
            (b"x-request-id", b"req-1"),
            (b"x-correlation-id", b"corr-1"),
        ]
    )

    context = get_request_context(request)

    assert context == {"request_id": "req-1", "correlation_id": "corr-1"}


def test_attach_request_context_headers_sets_response_headers():
    request = _make_request(headers=[(b"x-request-id", b"req-1")])
    response = Response()

    attach_request_context_headers(response, request)

    assert response.headers[REQUEST_ID_HEADER] == "req-1"
    assert response.headers[CORRELATION_ID_HEADER] == "req-1"
