"""System routes: landing, health, readiness, metrics."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse

from landing_page import render_landing_page
from service_metrics import PROMETHEUS_CONTENT_TYPE, render_prometheus_metrics


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
        return plain_text_response(
            request,
            render_prometheus_metrics(),
            media_type=PROMETHEUS_CONTENT_TYPE,
        )
