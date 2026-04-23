"""System routes: landing, health, readiness, metrics."""

from __future__ import annotations

import hmac
import os

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse

from landing_page import render_landing_page
from observability_logging import SECURITY_LOGGER
from request_context import get_request_context
from service_metrics import PROMETHEUS_CONTENT_TYPE, record_auth_failure, render_prometheus_metrics


def register_system_routes(mcp, *, observed_route, html_response, json_response, plain_text_response, check_storage_readiness):
    @observed_route(mcp, "/", methods=["GET"], include_in_schema=False)
    async def landing_page(request: Request) -> HTMLResponse:
        return html_response(request, render_landing_page())

    @observed_route(mcp, "/healthz", methods=["GET"], include_in_schema=False)
    async def healthcheck(request: Request) -> JSONResponse:
        return json_response(
            request,
            {
                "status": "ok",
                "probe": "liveness",
                "service": "vetmanager-mcp",
            },
        )

    @observed_route(mcp, "/readyz", methods=["GET"], include_in_schema=False)
    async def readiness_check(request: Request) -> JSONResponse:
        is_ready, reason = await check_storage_readiness()
        return json_response(
            request,
            {
                "status": "ok" if is_ready else "degraded",
                "probe": "readiness",
                "service": "vetmanager-mcp",
                "checks": {
                    "storage": {
                        "status": "ok" if is_ready else "failed",
                        "reason": reason,
                    }
                },
            },
            status_code=200 if is_ready else 503,
        )

    @observed_route(mcp, "/metrics", methods=["GET"], include_in_schema=False)
    async def metrics_export(request: Request) -> PlainTextResponse:
        # Stage 111.1 (F1 super-review 2026-04-19): gate /metrics behind
        # optional METRICS_AUTH_TOKEN. When env var is set, require matching
        # `Authorization: Bearer <token>` header; otherwise 403. When env is
        # unset, endpoint stays open (backward compat for self-hosted dev).
        # Production deploys MUST set the token — see README security section.
        expected = (os.environ.get("METRICS_AUTH_TOKEN") or "").strip()
        if expected:
            header = request.headers.get("authorization", "")
            scheme, _, supplied = header.partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                supplied.strip(), expected
            ):
                record_auth_failure(source="metrics", reason="invalid_token")
                SECURITY_LOGGER.warning(
                    "Metrics authentication failed.",
                    extra={
                        "event_name": "metrics_auth_failed",
                        **get_request_context(request),
                    },
                )
                return plain_text_response(request, "forbidden", status_code=403)
        return plain_text_response(
            request,
            render_prometheus_metrics(),
            media_type=PROMETHEUS_CONTENT_TYPE,
        )
