"""Public web routes for landing page and account auth."""

from __future__ import annotations

from datetime import timezone
from html import escape
import os
from secrets import token_urlsafe
import time
from urllib.parse import parse_qs
from functools import wraps

from fastmcp import FastMCP
from sqlalchemy import func, select, text
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from exceptions import AuthError, HostResolutionError, RateLimitError, VetmanagerError
from landing_page import render_landing_page
from observability_logging import RUNTIME_LOGGER
from request_context import attach_request_context_headers
from service_token_service import issue_service_bearer_token, revoke_service_bearer_token
from service_metrics import (
    PROMETHEUS_CONTENT_TYPE,
    record_auth_failure,
    record_http_request,
    render_prometheus_metrics,
)
from storage import get_session_factory
from storage_models import Account, ServiceBearerToken, TokenUsageStat, VetmanagerConnection
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
)
from vetmanager_connection_service import (
    INTEGRATION_HEALTH_ACTIVE,
    INTEGRATION_HEALTH_REAUTH_REQUIRED,
    INTEGRATION_HEALTH_UNKNOWN,
    evaluate_connection_health,
    save_domain_api_key_connection,
    save_user_login_password_connection,
)
from web_auth import (
    SESSION_COOKIE_NAME,
    authenticate_account,
    clear_account_session_cookie,
    read_account_session_token,
    register_account,
    set_account_session_cookie,
)
from token_cleanup import sync_expired_tokens
from web_auth import normalize_account_email
from web_security import (
    CSRF_FIELD_NAME,
    CSRF_COOKIE_NAME,
    check_rate_limit,
    clear_rate_limit_key,
    create_csrf_token,
    ensure_csrf_cookie,
    get_rate_limit_config,
    get_request_ip,
    record_rate_limit_hit,
    read_csrf_token,
    validate_csrf_request,
)


def _hidden_csrf_input(csrf_token: str) -> str:
    return f'<input type="hidden" name="{CSRF_FIELD_NAME}" value="{escape(csrf_token)}">'


def _resolve_csrf_token(request: Request) -> str:
    return read_csrf_token(request.cookies.get(CSRF_COOKIE_NAME)) or create_csrf_token()


def _generate_csp_nonce() -> str:
    return token_urlsafe(16)


def _apply_security_headers(
    response: HTMLResponse | RedirectResponse,
    *,
    script_nonce: str | None = None,
) -> None:
    script_src = "script-src 'self'"
    if script_nonce:
        script_src += f" 'nonce-{script_nonce}'"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"{script_src}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
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
    payload: dict[str, object],
    *,
    status_code: int = 200,
) -> JSONResponse:
    response = JSONResponse(payload, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
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
                "error_type": type(exc).__name__,
            },
        )
        return False, "storage_unavailable"
    return True, "ok"


def _render_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f3efe4;
      --paper: rgba(255, 251, 244, 0.92);
      --ink: #1d2321;
      --muted: #58645f;
      --accent: #bb4d24;
      --line: rgba(29, 35, 33, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(47, 109, 115, 0.15), transparent 34%),
        linear-gradient(180deg, #faf5ea 0%, var(--bg) 100%);
      color: var(--ink);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      display: grid;
      place-items: center;
      padding: 24px;
    }}
    .card {{
      width: min(760px, 100%);
      border: 1px solid var(--line);
      border-radius: 30px;
      padding: 28px;
      background: var(--paper);
      box-shadow: 0 24px 72px rgba(58, 41, 22, 0.12);
      backdrop-filter: blur(14px);
    }}
    h1 {{
      margin: 0 0 14px;
      font: 700 clamp(2.2rem, 5vw, 3.4rem)/0.95 "Iowan Old Style", "Palatino Linotype", serif;
    }}
    p, li, label, input, select, button, a {{
      font-size: 1rem;
      line-height: 1.6;
    }}
    p, li, label {{ color: var(--muted); }}
    form {{
      display: grid;
      gap: 14px;
      margin-top: 18px;
    }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px 16px;
      background: rgba(255, 255, 255, 0.9);
      color: var(--ink);
    }}
    button, .link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 13px 18px;
      text-decoration: none;
      border: 0;
      cursor: pointer;
      font-weight: 700;
    }}
    button {{
      background: var(--accent);
      color: #fff9f3;
    }}
    .link {{
      color: var(--ink);
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.55);
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 18px;
    }}
    .error {{
      margin-top: 12px;
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(187, 77, 36, 0.12);
      color: #7d2d14;
    }}
    .success {{
      margin-top: 12px;
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(47, 109, 115, 0.12);
      color: #1f4b50;
    }}
    .panel-card {{
      margin-top: 18px;
      padding: 18px;
      border-radius: 22px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.68);
    }}
    .hint {{
      font-size: 0.95rem;
      color: var(--muted);
    }}
    .choice-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .choice-option {{
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 14px;
      background: rgba(255,255,255,0.72);
    }}
    .choice-option input {{
      width: auto;
      margin-right: 8px;
    }}
    .choice-option strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 6px;
    }}
    .choice-option p {{
      margin: 6px 0 0;
      font-size: 0.95rem;
    }}
    .field-panel[hidden] {{
      display: none;
    }}
    .token-flash {{
      margin-top: 20px;
      padding: 18px;
      border-radius: 24px;
      border: 1px solid rgba(47, 109, 115, 0.22);
      background: linear-gradient(180deg, rgba(47, 109, 115, 0.18), rgba(255,255,255,0.86));
      scroll-margin-top: 24px;
    }}
    .copy-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
      margin-top: 12px;
    }}
    .copy-input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 0.92rem;
      background: rgba(255,255,255,0.92);
      color: var(--ink);
    }}
    .copy-button {{
      white-space: nowrap;
    }}
    .copy-status {{
      min-height: 1.2em;
      margin-top: 10px;
      font-size: 0.92rem;
      color: #1f4b50;
    }}
    .grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin-top: 18px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 16px;
      background: rgba(255,255,255,0.64);
    }}
    .metric strong {{
      display: block;
      font-size: 1.8rem;
      color: var(--ink);
    }}
    .section-note {{
      margin-top: 8px;
      color: var(--muted);
    }}
    code {{
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 0.92rem;
    }}
    pre {{
      margin: 10px 0 0;
      padding: 14px;
      border-radius: 18px;
      overflow-x: auto;
      background: #1f2427;
      color: #f3ede4;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 18px;
      font-size: 0.95rem;
    }}
    th, td {{
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 700;
    }}
    @media (max-width: 780px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .choice-grid {{ grid-template-columns: 1fr; }}
      .copy-row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="card">{body}</main>
</body>
</html>"""


def _render_register_page(*, csrf_token: str, error: str | None = None, email: str = "") -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return _render_shell(
        "Регистрация аккаунта",
        f"""
        <h1>Регистрация аккаунта</h1>
        <p>Создайте account сервиса, который позже получит Vetmanager integration и Bearer-токены.</p>
        {error_html}
        <form method="post" action="/register">
          {_hidden_csrf_input(csrf_token)}
          <label>Email
            <input type="email" name="email" autocomplete="email" value="{escape(email)}" required>
          </label>
          <label>Пароль
            <input type="password" name="password" autocomplete="new-password" minlength="8" required>
          </label>
          <button type="submit">Создать аккаунт</button>
        </form>
        <div class="actions">
          <a class="link" href="/login">Уже есть аккаунт</a>
          <a class="link" href="/">На лендинг</a>
        </div>
        """,
    )


def _render_login_page(*, csrf_token: str, error: str | None = None, email: str = "") -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return _render_shell(
        "Вход в аккаунт",
        f"""
        <h1>Вход в аккаунт</h1>
        <p>Войдите в account сервиса, чтобы управлять интеграцией с Vetmanager и Bearer-токенами.</p>
        {error_html}
        <form method="post" action="/login">
          {_hidden_csrf_input(csrf_token)}
          <label>Email
            <input type="email" name="email" autocomplete="email" value="{escape(email)}" required>
          </label>
          <label>Пароль
            <input type="password" name="password" autocomplete="current-password" minlength="8" required>
          </label>
          <button type="submit">Войти</button>
        </form>
        <div class="actions">
          <a class="link" href="/register">Создать аккаунт</a>
          <a class="link" href="/">На лендинг</a>
        </div>
        """,
    )


def _render_account_page(
    account: Account,
    *,
    csrf_token: str,
    script_nonce: str,
    active_connection_count: int,
    bearer_token_count: int,
    active_connection: VetmanagerConnection | None,
    integration_health_status: str,
    integration_health_reason: str,
    bearer_tokens: list[dict[str, str | int]],
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
) -> str:
    selected_auth_mode = form_auth_mode or (
        active_connection.auth_mode if active_connection else VETMANAGER_AUTH_MODE_DOMAIN_API_KEY
    )
    domain_value = form_domain or (active_connection.domain if active_connection else "")
    show_domain_api_key_panel = selected_auth_mode == VETMANAGER_AUTH_MODE_DOMAIN_API_KEY
    show_user_token_panel = selected_auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN
    domain_input_attrs = 'data-panel-input="true" data-required-when-active="true"'
    api_key_input_attrs = 'data-panel-input="true" data-required-when-active="true"'
    login_input_attrs = 'data-panel-input="true" data-required-when-active="true"'
    password_input_attrs = 'data-panel-input="true" data-required-when-active="true"'
    if show_domain_api_key_panel:
        login_input_attrs += " disabled"
        password_input_attrs += " disabled"
    else:
        domain_input_attrs += " disabled"
        api_key_input_attrs += " disabled"
    onboarding_html = ""
    if active_connection is None:
        onboarding_html = """
        <div class="panel-card">
          <strong>Сначала подключите Vetmanager</strong>
          <p>После регистрации следующий шаг один: выбрать способ авторизации, подключить клинику и только потом выпускать Bearer-токены для AI-ассистента.</p>
        </div>
        """
    active_connection_html = """
        <p>Активная Vetmanager integration ещё не настроена. Следующий Bearer-токен этого account пока не сможет резолвить clinic credentials.</p>
    """
    if active_connection is not None:
        reauth_html = ""
        if integration_health_status == INTEGRATION_HEALTH_REAUTH_REQUIRED:
            reauth_html = """
        <div class="error">
          <strong>Повторная авторизация требуется</strong>
          <p>Сохранённый user token больше не работает. Обычно это происходит после смены пароля в Vetmanager. Выполните повторную авторизацию и обновите токен.</p>
        </div>
        """
        active_connection_html = f"""
        <p>Текущая активная integration:</p>
        <ul>
          <li><strong>Auth mode:</strong> <code>{escape(active_connection.auth_mode)}</code></li>
          <li><strong>Domain:</strong> <code>{escape(active_connection.domain or "n/a")}</code></li>
          <li><strong>Status:</strong> <code>{escape(active_connection.status)}</code></li>
          <li><strong>Health:</strong> <code>{escape(integration_health_status)}</code></li>
        </ul>
        <p>{escape(integration_health_reason)}</p>
        <p>Vetmanager credential хранится в зашифрованном виде и больше не показывается после сохранения.</p>
        {reauth_html}
        """
    error_html = f'<div class="error">{escape(integration_error)}</div>' if integration_error else ""
    success_html = (
        '<div class="success">{}</div>'.format(escape(integration_success))
        if integration_success
        else ""
    )
    token_error_html = f'<div class="error">{escape(token_error)}</div>' if token_error else ""
    token_success_html = (
        '<div class="success">{}</div>'.format(escape(token_success))
        if token_success
        else ""
    )
    issued_token_html = ""
    if issued_raw_token:
        issued_token_html = f"""
        <section class="token-flash" id="issued-token-panel">
          <strong>Новый Bearer token</strong>
          <p>Скопируйте его сейчас. После этого экран больше не сможет показать raw token повторно.</p>
          <div class="copy-row">
            <input class="copy-input" id="issued-token-value" type="text" readonly value="{escape(issued_raw_token)}">
            <button class="copy-button" id="issued-token-copy-button" type="button" data-copy-target="issued-token-value">Скопировать токен</button>
          </div>
          <div class="copy-status" id="issued-token-copy-status" aria-live="polite"></div>
        </section>
        """
    token_disabled = "disabled" if active_connection is None or integration_health_status != INTEGRATION_HEALTH_ACTIVE else ""
    token_note = (
        "<p>Сначала сохраните активную Vetmanager integration, затем можно выпускать Bearer-токены.</p>"
        if active_connection is None
        else (
            "<p>Сначала восстановите работоспособность Vetmanager integration, затем можно выпускать Bearer-токены.</p>"
            if integration_health_status != INTEGRATION_HEALTH_ACTIVE
            else "<p>После создания raw token показывается только один раз, а в storage сохраняется только hash и безопасный prefix.</p>"
        )
    )
    token_list_html = "<p>Токенов пока нет.</p>"
    if bearer_tokens:
        rows = []
        for token in bearer_tokens:
            action_html = "&mdash;"
            if str(token["status"]) == "active":
                action_html = (
                    f'<form method="post" action="/account/tokens/{token["id"]}/revoke">'
                    f'{_hidden_csrf_input(csrf_token)}'
                    '<button type="submit">Revoke</button>'
                    "</form>"
                )
            rows.append(
                "<tr>"
                f"<td>{escape(str(token['name']))}</td>"
                f"<td><code>{escape(str(token['token_prefix']))}</code></td>"
                f"<td><code>{escape(str(token['status']))}</code></td>"
                f"<td>{escape(str(token['expires_at']))}</td>"
                f"<td>{escape(str(token['last_used_at']))}</td>"
                f"<td>{escape(str(token['request_count']))}</td>"
                f"<td>{action_html}</td>"
                "</tr>"
            )
        token_list_html = (
            "<table>"
            "<thead><tr>"
            "<th>Name</th><th>Prefix</th><th>Status</th><th>Expires</th><th>Last used</th><th>Requests</th><th>Actions</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    return _render_shell(
        "Кабинет аккаунта",
        f"""
        <h1>Личный кабинет</h1>
        <p>Вы вошли как <strong>{escape(account.email)}</strong>. Здесь вы подключаете Vetmanager клиники, проверяете статус интеграции и выпускаете Bearer-токены для работы AI-ассистента.</p>
        {issued_token_html}
        {onboarding_html}
        <div class="metric">
          <span>Privacy и auth transparency</span>
          <p>Сервис не сохраняет бизнес-данные Vetmanager для постоянного хранения. Хранятся только технические данные интеграции и service bearer metadata, необходимые для авторизации и работы MCP runtime.</p>
          <p>логин и пароль Vetmanager не сохраняются: они используются только для получения user token. при смене пароля в Vetmanager сохранённый user token может стать невалидным, и тогда потребуется повторная авторизация.</p>
        </div>
        <div class="grid">
          <section class="metric">
            <span>Статус аккаунта</span>
            <strong>{escape(account.status)}</strong>
          </section>
          <section class="metric">
            <span>Активные интеграции</span>
            <strong>{active_connection_count}</strong>
          </section>
          <section class="metric">
            <span>Bearer-токены</span>
            <strong>{bearer_token_count}</strong>
          </section>
        </div>
        <h2>Vetmanager integration</h2>
        {error_html}
        {success_html}
        {active_connection_html}
        <form method="post" action="/account/integration" data-auth-wizard="true">
          {_hidden_csrf_input(csrf_token)}
          <div class="panel-card">
            <strong>Выберите способ авторизации Vetmanager</strong>
            <p class="section-note">Сначала выберите удобный способ подключения. Мы покажем только нужные поля для следующего шага.</p>
            <div class="choice-grid">
              <label class="choice-option" id="auth-mode-domain-api-key">
                <span>
                  <input type="radio" name="auth_mode" value="{VETMANAGER_AUTH_MODE_DOMAIN_API_KEY}" {"checked" if show_domain_api_key_panel else ""}>
                  <strong>Подключить по API key</strong>
                </span>
                <p>Подходит, если у вас уже есть рабочий Vetmanager REST API key и нужно быстро подключить клинику.</p>
              </label>
              <label class="choice-option" id="auth-mode-user-token">
                <span>
                  <input type="radio" name="auth_mode" value="{VETMANAGER_AUTH_MODE_USER_TOKEN}" {"checked" if show_user_token_panel else ""}>
                  <strong>Подключить по логину и паролю</strong>
                </span>
                <p>Используйте этот вариант, если сервис должен сам получить user token через login/password и дальше хранить только токен.</p>
              </label>
            </div>
          </div>
          <div class="panel-card field-panel" data-mode-panel="{VETMANAGER_AUTH_MODE_DOMAIN_API_KEY}" {"hidden" if not show_domain_api_key_panel else ""}>
            <strong>Шаг 2. Данные клиники для API key</strong>
            <label>Clinic domain
              <input type="text" name="domain" value="{escape(domain_value)}" placeholder="myclinic" {domain_input_attrs}>
            </label>
            <label>Vetmanager REST API key
              <input type="password" name="api_key" autocomplete="off" placeholder="API key" {api_key_input_attrs}>
            </label>
            <p class="hint">Этот вариант не требует логин и пароль пользователя Vetmanager. Достаточно домена клиники и REST API key.</p>
          </div>
          <div class="panel-card field-panel" data-mode-panel="{VETMANAGER_AUTH_MODE_USER_TOKEN}" {"hidden" if not show_user_token_panel else ""}>
            <strong>Шаг 2. Данные клиники для логина и пароля</strong>
            <label>Clinic domain
              <input type="text" name="domain" value="{escape(domain_value)}" placeholder="myclinic" {'' if show_user_token_panel else 'disabled'} data-panel-input="true" data-required-when-active="true">
            </label>
            <label>Vetmanager login
              <input type="text" name="vm_login" value="{escape(form_vm_login)}" autocomplete="username" placeholder="user login" {login_input_attrs}>
            </label>
            <label>Vetmanager password
              <input type="password" name="vm_password" autocomplete="current-password" placeholder="password" {password_input_attrs}>
            </label>
            <p class="hint">Для этого режима сервис использует логин и пароль только для получения нового user token. Эти данные не сохраняются в storage, логи и audit trail.</p>
          </div>
          <div class="actions">
            <button type="submit">Сохранить подключение</button>
            <button type="submit" formaction="/account/integration/reauth">Переавторизоваться и обновить токен</button>
          </div>
        </form>
        <h2>Bearer token issuance</h2>
        {token_error_html}
        {token_success_html}
        {token_note}
        <form method="post" action="/account/tokens">
          {_hidden_csrf_input(csrf_token)}
          <label>Token name
            <input type="text" name="token_name" value="{escape(token_name)}" placeholder="Cursor production" required {token_disabled}>
          </label>
          <label>Expires in days
            <input type="number" name="expires_in_days" value="{escape(token_expiry_days)}" min="1" placeholder="30" {token_disabled}>
          </label>
          <button type="submit" {token_disabled}>Выпустить Bearer token</button>
        </form>
        <h2>Current tokens</h2>
        <p>В списке показываются только безопасные поля. Raw token после создания больше не доступен.</p>
        {token_list_html}
        <p>Текущий MCP runtime использует только <code>Authorization: Bearer &lt;service_token&gt;</code>. Этот web account уже стал источником регистрации, интеграции и выпуска токенов; следующим шагом здесь появится полноценный token list UI.</p>
        <form method="post" action="/logout">
          {_hidden_csrf_input(csrf_token)}
          <button type="submit">Выйти</button>
        </form>
        <div class="actions">
          <a class="link" href="/">На лендинг</a>
        </div>
        <script nonce="{escape(script_nonce)}">
          (() => {{
            const wizard = document.querySelector('[data-auth-wizard="true"]');
            if (wizard) {{
              const radios = Array.from(wizard.querySelectorAll('input[name="auth_mode"]'));
              const panels = Array.from(wizard.querySelectorAll('[data-mode-panel]'));
              const updatePanels = () => {{
                const selected = radios.find((radio) => radio.checked)?.value || '{VETMANAGER_AUTH_MODE_DOMAIN_API_KEY}';
                for (const panel of panels) {{
                  const isActive = panel.getAttribute('data-mode-panel') === selected;
                  panel.hidden = !isActive;
                  const inputs = panel.querySelectorAll('[data-panel-input="true"]');
                  for (const input of inputs) {{
                    const shouldRequire = input.hasAttribute('data-required-when-active');
                    input.disabled = !isActive;
                    input.required = isActive && shouldRequire;
                  }}
                }}
              }};
              for (const radio of radios) {{
                radio.addEventListener('change', updatePanels);
              }}
              updatePanels();
            }}

            const copyButton = document.getElementById('issued-token-copy-button');
            const copyInput = document.getElementById('issued-token-value');
            const copyStatus = document.getElementById('issued-token-copy-status');
            if (copyButton && copyInput) {{
              copyButton.addEventListener('click', async () => {{
                try {{
                  await navigator.clipboard.writeText(copyInput.value);
                  if (copyStatus) copyStatus.textContent = 'Токен скопирован в буфер обмена.';
                }} catch (_error) {{
                  copyInput.focus();
                  copyInput.select();
                  if (copyStatus) copyStatus.textContent = 'Автокопирование недоступно. Токен выделен, его можно скопировать вручную.';
                }}
              }});
            }}

            const issuedPanel = document.getElementById('issued-token-panel');
            if (issuedPanel) {{
              issuedPanel.scrollIntoView({{ behavior: 'auto', block: 'start' }});
            }}
          }})();
        </script>
        """,
    )


MAX_FORM_PAYLOAD_BYTES = 100 * 1024  # 100 KB


class FormPayloadTooLarge(Exception):
    """Raised when form body exceeds MAX_FORM_PAYLOAD_BYTES."""


async def _read_form(request: Request) -> dict[str, str]:
    body = await request.body()
    if len(body) > MAX_FORM_PAYLOAD_BYTES:
        raise FormPayloadTooLarge("Form payload too large.")
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


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
                VetmanagerConnection.status == "active",
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
                VetmanagerConnection.status == "active",
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
                }
            )
        integration_health_status = INTEGRATION_HEALTH_UNKNOWN
        integration_health_reason = "Integration is not configured yet."
        if active_connection is not None:
            integration_health_status, integration_health_reason = await evaluate_connection_health(
                active_connection,
                encryption_key=os.environ.get("STORAGE_ENCRYPTION_KEY"),
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
        _render_account_page(
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
        ),
        status_code=status_code,
        with_csrf_cookie=True,
        csrf_token=csrf_token,
        script_nonce=script_nonce,
    )


def register_web_routes(mcp: FastMCP) -> None:
    """Register public web routes on top of the MCP HTTP app."""

    @_observed_custom_route(mcp, "/", methods=["GET"], include_in_schema=False)
    async def landing_page(request: Request) -> HTMLResponse:
        return _html_response(request, render_landing_page())

    @_observed_custom_route(mcp, "/healthz", methods=["GET"], include_in_schema=False)
    async def healthcheck(request: Request) -> JSONResponse:
        return _json_response(
            request,
            {
                "status": "ok",
                "probe": "liveness",
                "service": "vetmanager-mcp",
            },
        )

    @_observed_custom_route(mcp, "/readyz", methods=["GET"], include_in_schema=False)
    async def readiness_check(request: Request) -> JSONResponse:
        is_ready, reason = await _check_storage_readiness()
        return _json_response(
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

    @_observed_custom_route(mcp, "/metrics", methods=["GET"], include_in_schema=False)
    async def metrics_export(request: Request) -> PlainTextResponse:
        return _plain_text_response(
            request,
            render_prometheus_metrics(),
            media_type=PROMETHEUS_CONTENT_TYPE,
        )

    @_observed_custom_route(mcp, "/register", methods=["GET"], include_in_schema=False)
    async def register_page(request: Request) -> HTMLResponse:
        csrf_token = _resolve_csrf_token(request)
        return _html_response(
            request,
            _render_register_page(csrf_token=csrf_token),
            with_csrf_cookie=True,
            csrf_token=csrf_token,
        )

    @_observed_custom_route(mcp, "/register", methods=["POST"], include_in_schema=False)
    async def register_submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await _read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            csrf_token = _resolve_csrf_token(request)
            return _html_response(
                request,
                _render_register_page(
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
        try:
            check_rate_limit(
                "register",
                register_key,
                limit=register_limit,
                window_seconds=register_window,
            )
        except RateLimitError:
            csrf_token = _resolve_csrf_token(request)
            return _html_response(
                request,
                _render_register_page(
                    csrf_token=csrf_token,
                    error="Too many registration attempts.",
                    email=form.get("email", ""),
                ),
                status_code=429,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )

        record_rate_limit_hit("register", register_key, window_seconds=register_window)
        async with get_session_factory()() as session:
            try:
                account = await register_account(
                    session,
                    email=form.get("email", ""),
                    password=form.get("password", ""),
                )
            except ValueError as exc:
                csrf_token = _resolve_csrf_token(request)
                return _html_response(
                    request,
                    _render_register_page(
                        csrf_token=csrf_token,
                        error=str(exc),
                        email=form.get("email", ""),
                    ),
                    status_code=400,
                    with_csrf_cookie=True,
                    csrf_token=csrf_token,
                )

        response = _redirect_response(request, url="/account", status_code=303)
        set_account_session_cookie(response, account.id)
        return response

    @_observed_custom_route(mcp, "/login", methods=["GET"], include_in_schema=False)
    async def login_page(request: Request) -> HTMLResponse:
        csrf_token = _resolve_csrf_token(request)
        return _html_response(
            request,
            _render_login_page(csrf_token=csrf_token),
            with_csrf_cookie=True,
            csrf_token=csrf_token,
        )

    @_observed_custom_route(mcp, "/login", methods=["POST"], include_in_schema=False)
    async def login_submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await _read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            csrf_token = _resolve_csrf_token(request)
            return _html_response(
                request,
                _render_login_page(
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
        try:
            check_rate_limit(
                "login",
                login_key,
                limit=login_limit,
                window_seconds=login_window,
            )
        except RateLimitError:
            csrf_token = _resolve_csrf_token(request)
            return _html_response(
                request,
                _render_login_page(
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
            csrf_token = _resolve_csrf_token(request)
            record_auth_failure(source="web_login", reason="invalid_credentials")
            record_rate_limit_hit("login", login_key, window_seconds=login_window)
            return _html_response(
                request,
                _render_login_page(
                    csrf_token=csrf_token,
                    error="Invalid email or password.",
                    email=form.get("email", ""),
                ),
                status_code=401,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )

        clear_rate_limit_key("login", login_key)
        response = _redirect_response(request, url="/account", status_code=303)
        set_account_session_cookie(response, account.id)
        return response

    @_observed_custom_route(mcp, "/logout", methods=["POST"], include_in_schema=False)
    async def logout_submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await _read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            csrf_token = _resolve_csrf_token(request)
            return _html_response(
                request,
                _render_login_page(
                    csrf_token=csrf_token,
                    error=str(exc),
                ),
                status_code=403,
                with_csrf_cookie=True,
                csrf_token=csrf_token,
            )
        response = _redirect_response(request, url="/", status_code=303)
        clear_account_session_cookie(response)
        return response

    @_observed_custom_route(mcp, "/account", methods=["GET"], include_in_schema=False)
    async def account_page(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = _get_account_id_from_request(request)
        if account_id is None:
            response = _redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response
        return await _render_account_dashboard_response(request, account_id)

    @_observed_custom_route(mcp, "/account/integration", methods=["POST"], include_in_schema=False)
    async def account_integration_submit(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = _get_account_id_from_request(request)
        if account_id is None:
            response = _redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await _read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                integration_error=str(exc),
            )
        auth_mode = form.get("auth_mode", VETMANAGER_AUTH_MODE_DOMAIN_API_KEY).strip()
        domain = form.get("domain", "")
        vm_login = form.get("vm_login", "")
        vm_password = form.get("vm_password", "")

        try:
            async with get_session_factory()() as session:
                if auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
                    await save_user_login_password_connection(
                        session,
                        account_id=account_id,
                        domain=domain,
                        login=vm_login,
                        password=vm_password,
                        encryption_key=os.environ.get("STORAGE_ENCRYPTION_KEY"),
                    )
                else:
                    await save_domain_api_key_connection(
                        session,
                        account_id=account_id,
                        domain=domain,
                        api_key=form.get("api_key", ""),
                        encryption_key=os.environ.get("STORAGE_ENCRYPTION_KEY"),
                    )
        except (ValueError, AuthError, HostResolutionError, VetmanagerError) as exc:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                integration_error=str(exc),
                form_auth_mode=auth_mode,
                form_domain=domain,
            )

        return await _render_account_dashboard_response(
            request,
            account_id,
            integration_success="Vetmanager integration saved successfully.",
        )

    @_observed_custom_route(mcp, "/account/integration/reauth", methods=["POST"], include_in_schema=False)
    async def account_integration_reauth_submit(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = _get_account_id_from_request(request)
        if account_id is None:
            response = _redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await _read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                integration_error=str(exc),
            )
        auth_mode = form.get("auth_mode", VETMANAGER_AUTH_MODE_DOMAIN_API_KEY).strip()
        domain = form.get("domain", "")
        vm_login = form.get("vm_login", "")
        vm_password = form.get("vm_password", "")

        try:
            async with get_session_factory()() as session:
                if auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
                    await save_user_login_password_connection(
                        session,
                        account_id=account_id,
                        domain=domain,
                        login=vm_login,
                        password=vm_password,
                        encryption_key=os.environ.get("STORAGE_ENCRYPTION_KEY"),
                    )
                else:
                    await save_domain_api_key_connection(
                        session,
                        account_id=account_id,
                        domain=domain,
                        api_key=form.get("api_key", ""),
                        encryption_key=os.environ.get("STORAGE_ENCRYPTION_KEY"),
                    )
        except (ValueError, AuthError, HostResolutionError, VetmanagerError) as exc:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                integration_error=str(exc),
                form_auth_mode=auth_mode,
                form_domain=domain,
            )

        return await _render_account_dashboard_response(
            request,
            account_id,
            integration_success="Vetmanager integration re-authorized successfully.",
        )

    @_observed_custom_route(mcp, "/account/tokens", methods=["POST"], include_in_schema=False)
    async def account_token_submit(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = _get_account_id_from_request(request)
        if account_id is None:
            response = _redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await _read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                token_error=str(exc),
            )
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

        token_name = form.get("token_name", "")
        expiry_raw = form.get("expires_in_days", "").strip()

        if active_connection is None or integration_health_status != INTEGRATION_HEALTH_ACTIVE:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                token_error=(
                    "Configure Vetmanager integration before issuing bearer tokens."
                    if active_connection is None
                    else integration_health_reason
                ),
                token_name=token_name,
                token_expiry_days=expiry_raw,
            )

        try:
            expires_in_days = int(expiry_raw) if expiry_raw else None
            async with get_session_factory()() as session:
                _, raw_token = await issue_service_bearer_token(
                    session,
                    account_id=account_id,
                    name=token_name,
                    expires_in_days=expires_in_days,
                )
        except ValueError as exc:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                token_error=str(exc),
                token_name=token_name,
                token_expiry_days=expiry_raw,
            )

        return await _render_account_dashboard_response(
            request,
            account_id,
            token_success="Bearer token issued successfully.",
            issued_raw_token=raw_token,
        )

    @_observed_custom_route(
        mcp,
        "/account/tokens/{token_id:int}/revoke",
        methods=["POST"],
        include_in_schema=False,
    )
    async def account_token_revoke(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = _get_account_id_from_request(request)
        if account_id is None:
            response = _redirect_response(request, url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await _read_form(request)
        try:
            validate_csrf_request(request, form.get(CSRF_FIELD_NAME))
        except ValueError as exc:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=403,
                token_error=str(exc),
            )
        token_id = int(request.path_params["token_id"])
        try:
            async with get_session_factory()() as session:
                await revoke_service_bearer_token(
                    session,
                    account_id=account_id,
                    token_id=token_id,
                )
        except ValueError as exc:
            return await _render_account_dashboard_response(
                request,
                account_id,
                status_code=400,
                token_error=str(exc),
            )

        return await _render_account_dashboard_response(
            request,
            account_id,
            token_success="Bearer token revoked successfully.",
        )
