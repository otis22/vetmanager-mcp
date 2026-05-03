"""System routes: landing, health, readiness, metrics."""

from __future__ import annotations

import asyncio
import hmac
import os

import activation_telemetry
import storage
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse

from secrets import token_urlsafe

from landing_page import render_landing_page
from observability_logging import RUNTIME_LOGGER, SECURITY_LOGGER
from request_context import get_request_context
from service_metrics import PROMETHEUS_CONTENT_TYPE, record_auth_failure, render_prometheus_metrics

# Stage 153 (F15): bounded timeout so /readyz never hangs the orchestrator if
# the storage probe stalls. Module-level so tests can monkeypatch.
READINESS_CHECK_TIMEOUT_SECONDS = 3.0
ACTIVATION_TELEMETRY_SCAN_TIMEOUT_SECONDS = 2.0
# Stage 153 (F15): module-level slot so tests can monkeypatch the storage probe.
# `register_system_routes` writes here at registration time; the handler reads
# from the module at call time (late binding through closure).
check_storage_readiness = None


def register_system_routes(mcp, *, observed_route, html_response, json_response, plain_text_response, check_storage_readiness):
    globals()["check_storage_readiness"] = check_storage_readiness

    async def _scan_activation_telemetry() -> None:
        async with storage.get_session_factory()() as session:
            await activation_telemetry.scan_activation_telemetry(session)

    @observed_route(mcp, "/", methods=["GET"], include_in_schema=False)
    async def landing_page(request: Request) -> HTMLResponse:
        # Stage 148: inline <script> in landing requires per-response nonce so
        # the strict `script-src 'self' 'nonce-...'` CSP allows it. Without
        # this, prod CSP blocks the script and tab/copy interaction breaks.
        nonce = token_urlsafe(16)
        return html_response(
            request,
            render_landing_page(script_nonce=nonce),
            script_nonce=nonce,
        )

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
        # Read late-bound module attr so tests can monkeypatch the probe.
        # CancelledError must propagate; only TimeoutError becomes 503.
        probe = globals()["check_storage_readiness"]
        if probe is None:
            raise RuntimeError("readiness_check called before register_system_routes installed the probe")
        try:
            is_ready, reason = await asyncio.wait_for(
                probe(),
                timeout=READINESS_CHECK_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            is_ready, reason = False, "storage_check_timeout"
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
            try:
                await asyncio.wait_for(
                    _scan_activation_telemetry(),
                    timeout=ACTIVATION_TELEMETRY_SCAN_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                RUNTIME_LOGGER.warning(
                    "Activation telemetry scan failed.",
                    extra={
                        "event_name": "activation_telemetry_scan_failed",
                        "error_class": exc.__class__.__name__,
                        **get_request_context(request),
                    },
                )
        return plain_text_response(
            request,
            render_prometheus_metrics(),
            media_type=PROMETHEUS_CONTENT_TYPE,
        )
