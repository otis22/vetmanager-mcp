"""Public web routes for landing page and account auth.

This module is the orchestrator — it wires shared helpers to route modules.
Route handlers live in web_routes_system.py, web_routes_auth.py, web_routes_account.py.
HTML rendering lives in web_html.py.
"""

from __future__ import annotations

from datetime import timezone
import os
from secrets import token_urlsafe
import time
from urllib.parse import parse_qs
from functools import wraps

from fastmcp import FastMCP
from sqlalchemy import func, select, text
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from observability_logging import RUNTIME_LOGGER
from request_context import attach_request_context_headers
from secret_manager import get_storage_encryption_key
from service_metrics import record_http_request
from storage import get_session_factory
from storage_models import (
    CONNECTION_STATUS_ACTIVE,
    Account,
    ServiceBearerToken,
    TokenUsageStat,
    VetmanagerConnection,
)
from token_cleanup import sync_expired_tokens
from vetmanager_auth import VETMANAGER_AUTH_MODE_DOMAIN_API_KEY
from vetmanager_connection_service import (
    INTEGRATION_HEALTH_UNKNOWN,
    evaluate_connection_health,
)
from web_auth import SESSION_COOKIE_NAME, read_account_session_token, clear_account_session_cookie
from web_html import render_account_page
from web_routes_account import register_account_routes
from web_routes_auth import register_auth_routes
from web_routes_system import register_system_routes
from web_security import (
    CSRF_COOKIE_NAME,
    create_csrf_token,
    ensure_csrf_cookie,
    read_csrf_token,
)


# ── Shared helpers ───────────────────────────────────────────────────────────


def _generate_csp_nonce() -> str:
    return token_urlsafe(16)


def _resolve_csrf_token(request: Request) -> str:
    return read_csrf_token(request.cookies.get(CSRF_COOKIE_NAME)) or create_csrf_token()


def _apply_security_headers(
    response: HTMLResponse | RedirectResponse,
    *,
    script_nonce: str | None = None,
) -> None:
    script_src = "script-src 'self'"
    if script_nonce:
        script_src += f" 'nonce-{script_nonce}'"
    csp = (
        "default-src 'self'; "
        f"{script_src}; "
        # Note: 'unsafe-inline' required for inline style="" attributes in
        # landing_page.py/web.py (~41 occurrences). Tracked as TD-55-02.
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    if os.environ.get("WEB_ENABLE_HSTS", "").strip().lower() in {"1", "true", "yes", "on"}:
        csp += "; upgrade-insecure-requests"
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if os.environ.get("WEB_ENABLE_HSTS", "").strip().lower() in {"1", "true", "yes", "on"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


def _html_response(
    request: Request,
    content: str,
    *,
    status_code: int = 200,
    with_csrf_cookie: bool = False,
    csrf_token: str | None = None,
    script_nonce: str | None = None,
) -> HTMLResponse:
    response = HTMLResponse(content, status_code=status_code)
    _apply_security_headers(response, script_nonce=script_nonce)
    attach_request_context_headers(response, request)
    if with_csrf_cookie:
        ensure_csrf_cookie(
            response,
            existing_token=csrf_token or request.cookies.get(CSRF_COOKIE_NAME),
        )
    return response


def _redirect_response(
    request: Request,
    *,
    url: str,
    status_code: int = 303,
    with_csrf_cookie: bool = False,
) -> RedirectResponse:
    response = RedirectResponse(url=url, status_code=status_code)
    _apply_security_headers(response)
    attach_request_context_headers(response, request)
    if with_csrf_cookie:
        ensure_csrf_cookie(response, existing_token=request.cookies.get(CSRF_COOKIE_NAME))
    return response


def _json_response(
    request: Request,
    payload: dict,
    *,
    status_code: int = 200,
) -> JSONResponse:
    response = JSONResponse(payload, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    attach_request_context_headers(response, request)
    return response


def _plain_text_response(
    request: Request,
    content: str,
    *,
    status_code: int = 200,
    media_type: str = "text/plain",
) -> PlainTextResponse:
    response = PlainTextResponse(content, status_code=status_code, media_type=media_type)
    response.headers["Cache-Control"] = "no-store"
    attach_request_context_headers(response, request)
    return response


MAX_FORM_PAYLOAD_BYTES = 100 * 1024  # 100 KB


class FormPayloadTooLarge(Exception):
    """Raised when form body exceeds MAX_FORM_PAYLOAD_BYTES."""


async def _read_form(request: Request) -> dict[str, str]:
    body = await request.body()
    if len(body) > MAX_FORM_PAYLOAD_BYTES:
        raise FormPayloadTooLarge("Form payload too large.")
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _observed_custom_route(
    mcp: FastMCP,
    path: str,
    *,
    methods: list[str],
    include_in_schema: bool = False,
):
    """Register route with automatic HTTP metrics for latency and status totals."""

    def _decorator(func):
        @wraps(func)
        async def _wrapped(request: Request, *args, **kwargs):
            started_at = time.perf_counter()
            status_code = 500
            try:
                response = await func(request, *args, **kwargs)
                status_code = getattr(response, "status_code", 500)
                return response
            except FormPayloadTooLarge:
                status_code = 413
                return PlainTextResponse("Payload too large.", status_code=413)
            finally:
                record_http_request(
                    route=path,
                    method=request.method,
                    status_code=status_code,
                    duration_seconds=time.perf_counter() - started_at,
                )

        return mcp.custom_route(path, methods=methods, include_in_schema=include_in_schema)(_wrapped)

    return _decorator


async def _check_storage_readiness() -> tuple[bool, str]:
    try:
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        RUNTIME_LOGGER.warning(
            "Readiness probe detected unavailable storage.",
            extra={
                "event_name": "storage_readiness_failed",
                "error": str(exc),
            },
        )
        return False, "storage_unavailable"
    return True, "ok"


def _get_account_id_from_request(request: Request) -> int | None:
    return read_account_session_token(request.cookies.get(SESSION_COOKIE_NAME))


def _format_dt(value) -> str:
    if value is None:
        return "Never"
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def _load_account_dashboard(
    account_id: int,
) -> tuple[Account | None, int, int, VetmanagerConnection | None, str, str, list[dict[str, str | int]]]:
    async with get_session_factory()() as session:
        await sync_expired_tokens(session, account_id=account_id)
        account = await session.get(Account, account_id)
        if account is None:
            return None, 0, 0, None, "unknown", "Integration is not configured yet.", []

        active_connection_count = await session.scalar(
            select(func.count())
            .select_from(VetmanagerConnection)
            .where(
                VetmanagerConnection.account_id == account.id,
                VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE,
            )
        )
        bearer_token_count = await session.scalar(
            select(func.count())
            .select_from(ServiceBearerToken)
            .where(ServiceBearerToken.account_id == account.id)
        )
        active_connection = await session.scalar(
            select(VetmanagerConnection)
            .where(
                VetmanagerConnection.account_id == account.id,
                VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE,
            )
            .order_by(VetmanagerConnection.id.desc())
        )
        tokens = (
            await session.execute(
                select(ServiceBearerToken)
                .where(ServiceBearerToken.account_id == account.id)
                .order_by(ServiceBearerToken.created_at.desc())
            )
        ).scalars().all()
        usage_by_token_id: dict[int, TokenUsageStat] = {}
        if tokens:
            token_ids = [token.id for token in tokens]
            usage_rows = (
                await session.execute(
                    select(TokenUsageStat).where(TokenUsageStat.bearer_token_id.in_(token_ids))
                )
            ).scalars().all()
            usage_by_token_id = {row.bearer_token_id: row for row in usage_rows}
        token_view = []
        for token in tokens:
            usage = usage_by_token_id.get(token.id)
            token_view.append(
                {
                    "id": token.id,
                    "name": token.name,
                    "token_prefix": token.token_prefix,
                    "status": token.status,
                    "expires_at": _format_dt(token.expires_at) if token.expires_at else "No expiry",
                    "last_used_at": _format_dt(token.last_used_at or (usage.last_used_at if usage else None)),
                    "request_count": int(usage.request_count if usage else 0),
                    "ip_mask": token.get_allowed_ip_mask(),
                }
            )
        integration_health_status = INTEGRATION_HEALTH_UNKNOWN
        integration_health_reason = "Integration is not configured yet."
        if active_connection is not None:
            integration_health_status, integration_health_reason = await evaluate_connection_health(
                active_connection,
                encryption_key=get_storage_encryption_key(),
            )
        return (
            account,
            int(active_connection_count or 0),
            int(bearer_token_count or 0),
            active_connection,
            integration_health_status,
            integration_health_reason,
            token_view,
        )


async def _render_account_dashboard_response(
    request: Request,
    account_id: int,
    *,
    status_code: int = 200,
    integration_error: str | None = None,
    integration_success: str | None = None,
    form_auth_mode: str = VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    form_domain: str = "",
    form_vm_login: str = "",
    token_error: str | None = None,
    token_success: str | None = None,
    issued_raw_token: str | None = None,
    token_name: str = "",
    token_expiry_days: str = "",
    ip_mask: str = "*.*.*.*",
) -> HTMLResponse | RedirectResponse:
    csrf_token = _resolve_csrf_token(request)
    script_nonce = _generate_csp_nonce()
    (
        account,
        active_connection_count,
        bearer_token_count,
        active_connection,
        integration_health_status,
        integration_health_reason,
        bearer_tokens,
    ) = await _load_account_dashboard(account_id)
    if account is None:
        response = _redirect_response(request, url="/login", status_code=303)
        clear_account_session_cookie(response)
        return response
    return _html_response(
        request,
        render_account_page(
            account,
            csrf_token=csrf_token,
            script_nonce=script_nonce,
            active_connection_count=active_connection_count,
            bearer_token_count=bearer_token_count,
            active_connection=active_connection,
            integration_health_status=integration_health_status,
            integration_health_reason=integration_health_reason,
            bearer_tokens=bearer_tokens,
            integration_error=integration_error,
            integration_success=integration_success,
            form_auth_mode=form_auth_mode,
            form_domain=form_domain,
            form_vm_login=form_vm_login,
            token_error=token_error,
            token_success=token_success,
            issued_raw_token=issued_raw_token,
            token_name=token_name,
            token_expiry_days=token_expiry_days,
            ip_mask=ip_mask,
        ),
        status_code=status_code,
        with_csrf_cookie=True,
        csrf_token=csrf_token,
        script_nonce=script_nonce,
    )


# ── Route registration orchestrator ─────────────────────────────────────────


def register_web_routes(mcp: FastMCP) -> None:
    """Register public web routes on top of the MCP HTTP app."""

    register_system_routes(
        mcp,
        observed_route=_observed_custom_route,
        html_response=_html_response,
        json_response=_json_response,
        plain_text_response=_plain_text_response,
        check_storage_readiness=_check_storage_readiness,
    )

    register_auth_routes(
        mcp,
        observed_route=_observed_custom_route,
        html_response=_html_response,
        redirect_response=_redirect_response,
        read_form=_read_form,
        resolve_csrf_token=_resolve_csrf_token,
    )

    register_account_routes(
        mcp,
        observed_route=_observed_custom_route,
        redirect_response=_redirect_response,
        read_form=_read_form,
        get_account_id_from_request=_get_account_id_from_request,
        render_account_dashboard_response=_render_account_dashboard_response,
        load_account_dashboard=_load_account_dashboard,
    )
