"""Auth routes: register, login, logout."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from exceptions import RateLimitError
from observability_logging import RUNTIME_LOGGER
from request_context import get_current_request_context
from service_metrics import record_auth_failure, record_business_event
from storage import get_session_factory
from web_auth import (
    authenticate_account,
    clear_account_session_cookie,
    normalize_account_email,
    register_account,
    set_account_session_cookie,
)
from web_html import render_login_page, render_register_page
from web_security import (
    CSRF_FIELD_NAME,
    check_rate_limit,
    clear_rate_limit_key,
    get_rate_limit_config,
    get_request_ip,
    record_rate_limit_hit,
    validate_csrf_request,
)


def register_auth_routes(
    mcp,
    *,
    observed_route,
    html_response,
    redirect_response,
    read_form,
    resolve_csrf_token,
):
    @observed_route(mcp, "/register", methods=["GET"], include_in_schema=False)
    async def register_page(request: Request) -> HTMLResponse:
        csrf_token = resolve_csrf_token(request)
        return html_response(
            request,
            render_register_page(csrf_token=csrf_token),
            with_csrf_cookie=True,
            csrf_token=csrf_token,
        )

    @observed_route(mcp, "/register", methods=["POST"], include_in_schema=False)
    async def register_submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            csrf_token = resolve_csrf_token(request)
            return html_response(
                request,
                render_register_page(
                    csrf_token=csrf_token,
                    error=str(exc),
                    email=form.get("email", ""),
                ),
                status_code=403,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )

        register_limit, register_window = get_rate_limit_config(
            "WEB_REGISTER_RATE_LIMIT",
            default_attempts=10,
            default_window_seconds=60,
        )
        register_key = get_request_ip(request)
        register_email_key = f"email:{normalize_account_email(form.get('email', ''))}"
        try:
            check_rate_limit(
                "register",
                register_key,
                limit=register_limit,
                window_seconds=register_window,
            )
            check_rate_limit(
                "register_email",
                register_email_key,
                limit=3,
                window_seconds=3600,
            )
        except RateLimitError:
            # Stage 107.3 (obs H12): rate-limited registration gets a failure
            # metric so SRE can alert on registration spikes (credential
            # stuffing, bot signup).
            record_auth_failure(source="web_register", reason="rate_limited")
            csrf_token = resolve_csrf_token(request)
            return html_response(
                request,
                render_register_page(
                    csrf_token=csrf_token,
                    error="Too many registration attempts.",
                    email=form.get("email", ""),
                ),
                status_code=429,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )

        record_rate_limit_hit("register", register_key, window_seconds=register_window)
        record_rate_limit_hit("register_email", register_email_key, window_seconds=3600)
        async with get_session_factory()() as session:
            try:
                account = await register_account(
                    session,
                    email=form.get("email", ""),
                    password=form.get("password", ""),
                )
            except ValueError as exc:
                # Stage 107.3: validation error (duplicate email, weak
                # password) gets its own failure metric label.
                record_auth_failure(source="web_register", reason="validation_error")
                csrf_token = resolve_csrf_token(request)
                return html_response(
                    request,
                    render_register_page(
                        csrf_token=csrf_token,
                        error=str(exc),
                        email=form.get("email", ""),
                    ),
                    status_code=400,
                    with_csrf_cookie=True,
                    csrf_token=csrf_token,
                )

        # Stage 107.3: structured business-event log for successful
        # registration so audit can answer "when did account X appear".
        # Stage 110.2: also bump the process-local Prometheus counter.
        # Stage 112.4 (super-review 2026-04-19): explicit correlation_id
        # so log aggregator can join event to inbound HTTP request even
        # when RequestContextLogFilter silently omits the field.
        _ctx = get_current_request_context() or {}
        RUNTIME_LOGGER.info(
            "Account registered",
            extra={
                "event_name": "account_registered",
                "account_id": account.id,
                "correlation_id": _ctx.get("correlation_id"),
            },
        )
        record_business_event("account_registered")

        response = redirect_response(request, url="/account", status_code=303)
        set_account_session_cookie(response, account.id)
        return response

    @observed_route(mcp, "/login", methods=["GET"], include_in_schema=False)
    async def login_page(request: Request) -> HTMLResponse:
        csrf_token = resolve_csrf_token(request)
        return html_response(
            request,
            render_login_page(csrf_token=csrf_token),
            with_csrf_cookie=True,
            csrf_token=csrf_token,
        )

    @observed_route(mcp, "/login", methods=["POST"], include_in_schema=False)
    async def login_submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            csrf_token = resolve_csrf_token(request)
            return html_response(
                request,
                render_login_page(
                    csrf_token=csrf_token,
                    error=str(exc),
                    email=form.get("email", ""),
                ),
                status_code=403,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )

        login_limit, login_window = get_rate_limit_config(
            "WEB_LOGIN_RATE_LIMIT",
            default_attempts=5,
            default_window_seconds=60,
        )
        login_key = f"{get_request_ip(request)}:{normalize_account_email(form.get('email', ''))}"
        lockout_email_key = f"email:{normalize_account_email(form.get('email', ''))}"
        try:
            check_rate_limit(
                "login",
                login_key,
                limit=login_limit,
                window_seconds=login_window,
            )
            check_rate_limit(
                "login_lockout",
                lockout_email_key,
                limit=10,
                window_seconds=900,
            )
        except RateLimitError:
            # Stage 111.3 (F5 super-review 2026-04-19): emit auth-failure
            # metric symmetrically with the register path (stage 107.3)
            # so credential-stuffing that trips login lockout is visible
            # in Grafana instead of silently invisible.
            record_auth_failure(source="web_login", reason="rate_limited")
            csrf_token = resolve_csrf_token(request)
            return html_response(
                request,
                render_login_page(
                    csrf_token=csrf_token,
                    error="Too many login attempts.",
                    email=form.get("email", ""),
                ),
                status_code=429,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )

        async with get_session_factory()() as session:
            account = await authenticate_account(
                session,
                email=form.get("email", ""),
                password=form.get("password", ""),
            )

        if account is None:
            csrf_token = resolve_csrf_token(request)
            record_auth_failure(source="web_login", reason="invalid_credentials")
            record_rate_limit_hit("login", login_key, window_seconds=login_window)
            record_rate_limit_hit("login_lockout", lockout_email_key, window_seconds=900)
            return html_response(
                request,
                render_login_page(
                    csrf_token=csrf_token,
                    error="Invalid email or password.",
                    email=form.get("email", ""),
                ),
                status_code=401,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )

        clear_rate_limit_key("login", login_key)
        clear_rate_limit_key("login_lockout", lockout_email_key)
        # Stage 112.4: explicit correlation_id (see register-path above).
        _ctx = get_current_request_context() or {}
        RUNTIME_LOGGER.info(
            "Web login succeeded",
            extra={
                "event_name": "web_login_succeeded",
                "account_id": account.id,
                "correlation_id": _ctx.get("correlation_id"),
            },
        )
        record_business_event("web_login_succeeded")
        response = redirect_response(request, url="/account", status_code=303)
        set_account_session_cookie(response, account.id)
        return response

    @observed_route(mcp, "/logout", methods=["POST"], include_in_schema=False)
    async def logout_submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            csrf_token = resolve_csrf_token(request)
            return html_response(
                request,
                render_login_page(
                    csrf_token=csrf_token,
                    error=str(exc),
                ),
                status_code=403,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )
        response = redirect_response(request, url="/", status_code=303)
        clear_account_session_cookie(response)
        return response
