"""Public web routes for landing page and account auth."""

from __future__ import annotations

from datetime import timezone
from html import escape
import os
from urllib.parse import parse_qs

from fastmcp import FastMCP
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from exceptions import AuthError, HostResolutionError, VetmanagerError
from landing_page import render_landing_page
from service_token_service import issue_service_bearer_token
from storage import get_session_factory
from storage_models import Account, ServiceBearerToken, TokenUsageStat, VetmanagerConnection
from vetmanager_connection_service import save_domain_api_key_connection
from web_auth import (
    SESSION_COOKIE_NAME,
    authenticate_account,
    clear_account_session_cookie,
    read_account_session_token,
    register_account,
    set_account_session_cookie,
)


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
    p, li, label, input, button, a {{
      font-size: 1rem;
      line-height: 1.6;
    }}
    p, li, label {{ color: var(--muted); }}
    form {{
      display: grid;
      gap: 14px;
      margin-top: 18px;
    }}
    input {{
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
    }}
  </style>
</head>
<body>
  <main class="card">{body}</main>
</body>
</html>"""


def _render_register_page(*, error: str | None = None, email: str = "") -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return _render_shell(
        "Регистрация аккаунта",
        f"""
        <h1>Регистрация аккаунта</h1>
        <p>Создайте account сервиса, который позже получит Vetmanager integration и Bearer-токены.</p>
        {error_html}
        <form method="post" action="/register">
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


def _render_login_page(*, error: str | None = None, email: str = "") -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return _render_shell(
        "Вход в аккаунт",
        f"""
        <h1>Вход в аккаунт</h1>
        <p>Войдите в account сервиса, чтобы управлять интеграцией с Vetmanager и Bearer-токенами.</p>
        {error_html}
        <form method="post" action="/login">
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
    active_connection_count: int,
    bearer_token_count: int,
    active_connection: VetmanagerConnection | None,
    bearer_tokens: list[dict[str, str | int]],
    integration_error: str | None = None,
    integration_success: str | None = None,
    form_domain: str = "",
    token_error: str | None = None,
    token_success: str | None = None,
    issued_raw_token: str | None = None,
    token_name: str = "",
    token_expiry_days: str = "",
) -> str:
    active_connection_html = """
        <p>Активная Vetmanager integration ещё не настроена. Следующий Bearer-токен этого account пока не сможет резолвить clinic credentials.</p>
    """
    if active_connection is not None:
        active_connection_html = f"""
        <p>Текущая активная integration:</p>
        <ul>
          <li><strong>Auth mode:</strong> <code>{escape(active_connection.auth_mode)}</code></li>
          <li><strong>Domain:</strong> <code>{escape(active_connection.domain or "n/a")}</code></li>
          <li><strong>Status:</strong> <code>{escape(active_connection.status)}</code></li>
        </ul>
        <p>Vetmanager API key хранится в зашифрованном виде и больше не показывается после сохранения.</p>
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
        <div class="success">
          <strong>Новый Bearer token</strong>
          <p>Скопируйте его сейчас. После этого экран больше не сможет показать raw token повторно.</p>
          <pre><code>{escape(issued_raw_token)}</code></pre>
        </div>
        """
    token_disabled = "disabled" if active_connection is None else ""
    token_note = (
        "<p>Сначала сохраните активную Vetmanager integration, затем можно выпускать Bearer-токены.</p>"
        if active_connection is None
        else "<p>После создания raw token показывается только один раз, а в storage сохраняется только hash и безопасный prefix.</p>"
    )
    token_list_html = "<p>Токенов пока нет.</p>"
    if bearer_tokens:
        rows = []
        for token in bearer_tokens:
            rows.append(
                "<tr>"
                f"<td>{escape(str(token['name']))}</td>"
                f"<td><code>{escape(str(token['token_prefix']))}</code></td>"
                f"<td><code>{escape(str(token['status']))}</code></td>"
                f"<td>{escape(str(token['expires_at']))}</td>"
                f"<td>{escape(str(token['last_used_at']))}</td>"
                f"<td>{escape(str(token['request_count']))}</td>"
                "</tr>"
            )
        token_list_html = (
            "<table>"
            "<thead><tr>"
            "<th>Name</th><th>Prefix</th><th>Status</th><th>Expires</th><th>Last used</th><th>Requests</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    return _render_shell(
        "Кабинет аккаунта",
        f"""
        <h1>Личный кабинет</h1>
        <p>Вы вошли как <strong>{escape(account.email)}</strong>. Bearer-only runtime уже активен, а следующие шаги web-контура добавят настройку Vetmanager integration и выпуск токенов прямо из кабинета.</p>
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
        <form method="post" action="/account/integration">
          <label>Clinic domain
            <input type="text" name="domain" value="{escape(form_domain or (active_connection.domain if active_connection else ''))}" placeholder="myclinic" required>
          </label>
          <label>Vetmanager REST API key
            <input type="password" name="api_key" autocomplete="off" placeholder="rest-api-key" required>
          </label>
          <button type="submit">Сохранить интеграцию</button>
        </form>
        <h2>Bearer token issuance</h2>
        {token_error_html}
        {token_success_html}
        {issued_token_html}
        {token_note}
        <form method="post" action="/account/tokens">
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
          <button type="submit">Выйти</button>
        </form>
        <div class="actions">
          <a class="link" href="/">На лендинг</a>
        </div>
        """,
    )


async def _read_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
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
) -> tuple[Account | None, int, int, VetmanagerConnection | None, list[dict[str, str | int]]]:
    async with get_session_factory()() as session:
        account = await session.get(Account, account_id)
        if account is None:
            return None, 0, 0, None, []

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
                    "name": token.name,
                    "token_prefix": token.token_prefix,
                    "status": token.status,
                    "expires_at": _format_dt(token.expires_at) if token.expires_at else "No expiry",
                    "last_used_at": _format_dt(token.last_used_at or (usage.last_used_at if usage else None)),
                    "request_count": int(usage.request_count if usage else 0),
                }
            )
        return (
            account,
            int(active_connection_count or 0),
            int(bearer_token_count or 0),
            active_connection,
            token_view,
        )


def register_web_routes(mcp: FastMCP) -> None:
    """Register public web routes on top of the MCP HTTP app."""

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def landing_page(request: Request) -> HTMLResponse:
        return HTMLResponse(render_landing_page())

    @mcp.custom_route("/register", methods=["GET"], include_in_schema=False)
    async def register_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_register_page())

    @mcp.custom_route("/register", methods=["POST"], include_in_schema=False)
    async def register_submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await _read_form(request)
        async with get_session_factory()() as session:
            try:
                account = await register_account(
                    session,
                    email=form.get("email", ""),
                    password=form.get("password", ""),
                )
            except ValueError as exc:
                return HTMLResponse(
                    _render_register_page(error=str(exc), email=form.get("email", "")),
                    status_code=400,
                )

        response = RedirectResponse(url="/account", status_code=303)
        set_account_session_cookie(response, account.id)
        return response

    @mcp.custom_route("/login", methods=["GET"], include_in_schema=False)
    async def login_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_login_page())

    @mcp.custom_route("/login", methods=["POST"], include_in_schema=False)
    async def login_submit(request: Request) -> HTMLResponse | RedirectResponse:
        form = await _read_form(request)
        async with get_session_factory()() as session:
            account = await authenticate_account(
                session,
                email=form.get("email", ""),
                password=form.get("password", ""),
            )

        if account is None:
            return HTMLResponse(
                _render_login_page(
                    error="Invalid email or password.",
                    email=form.get("email", ""),
                ),
                status_code=401,
            )

        response = RedirectResponse(url="/account", status_code=303)
        set_account_session_cookie(response, account.id)
        return response

    @mcp.custom_route("/logout", methods=["POST"], include_in_schema=False)
    async def logout_submit(request: Request) -> RedirectResponse:
        response = RedirectResponse(url="/", status_code=303)
        clear_account_session_cookie(response)
        return response

    @mcp.custom_route("/account", methods=["GET"], include_in_schema=False)
    async def account_page(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = _get_account_id_from_request(request)
        if account_id is None:
            response = RedirectResponse(url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        account, active_connection_count, bearer_token_count, active_connection, bearer_tokens = await _load_account_dashboard(
            account_id
        )
        if account is None:
            response = RedirectResponse(url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        return HTMLResponse(
            _render_account_page(
                account,
                active_connection_count=active_connection_count,
                bearer_token_count=bearer_token_count,
                active_connection=active_connection,
                bearer_tokens=bearer_tokens,
            )
        )

    @mcp.custom_route("/account/integration", methods=["POST"], include_in_schema=False)
    async def account_integration_submit(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = _get_account_id_from_request(request)
        if account_id is None:
            response = RedirectResponse(url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await _read_form(request)
        domain = form.get("domain", "")
        api_key = form.get("api_key", "")

        try:
            async with get_session_factory()() as session:
                await save_domain_api_key_connection(
                    session,
                    account_id=account_id,
                    domain=domain,
                    api_key=api_key,
                    encryption_key=os.environ.get("STORAGE_ENCRYPTION_KEY"),
                )
        except (ValueError, AuthError, HostResolutionError, VetmanagerError) as exc:
            account, active_connection_count, bearer_token_count, active_connection, bearer_tokens = await _load_account_dashboard(
                account_id
            )
            if account is None:
                response = RedirectResponse(url="/login", status_code=303)
                clear_account_session_cookie(response)
                return response
            return HTMLResponse(
                _render_account_page(
                    account,
                    active_connection_count=active_connection_count,
                    bearer_token_count=bearer_token_count,
                    active_connection=active_connection,
                    bearer_tokens=bearer_tokens,
                    integration_error=str(exc),
                    form_domain=domain,
                ),
                status_code=400,
            )

        account, active_connection_count, bearer_token_count, active_connection, bearer_tokens = await _load_account_dashboard(
            account_id
        )
        if account is None:
            response = RedirectResponse(url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response
        return HTMLResponse(
            _render_account_page(
                account,
                active_connection_count=active_connection_count,
                bearer_token_count=bearer_token_count,
                active_connection=active_connection,
                bearer_tokens=bearer_tokens,
                integration_success="Vetmanager integration saved successfully.",
            )
        )

    @mcp.custom_route("/account/tokens", methods=["POST"], include_in_schema=False)
    async def account_token_submit(request: Request) -> HTMLResponse | RedirectResponse:
        account_id = _get_account_id_from_request(request)
        if account_id is None:
            response = RedirectResponse(url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        account, active_connection_count, bearer_token_count, active_connection, bearer_tokens = await _load_account_dashboard(
            account_id
        )
        if account is None:
            response = RedirectResponse(url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response

        form = await _read_form(request)
        token_name = form.get("token_name", "")
        expiry_raw = form.get("expires_in_days", "").strip()

        if active_connection is None:
            return HTMLResponse(
                _render_account_page(
                    account,
                    active_connection_count=active_connection_count,
                    bearer_token_count=bearer_token_count,
                    active_connection=active_connection,
                    bearer_tokens=bearer_tokens,
                    token_error="Configure Vetmanager integration before issuing bearer tokens.",
                    token_name=token_name,
                    token_expiry_days=expiry_raw,
                ),
                status_code=400,
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
            account, active_connection_count, bearer_token_count, active_connection, bearer_tokens = await _load_account_dashboard(
                account_id
            )
            if account is None:
                response = RedirectResponse(url="/login", status_code=303)
                clear_account_session_cookie(response)
                return response
            return HTMLResponse(
                _render_account_page(
                    account,
                    active_connection_count=active_connection_count,
                    bearer_token_count=bearer_token_count,
                    active_connection=active_connection,
                    bearer_tokens=bearer_tokens,
                    token_error=str(exc),
                    token_name=token_name,
                    token_expiry_days=expiry_raw,
                ),
                status_code=400,
            )

        account, active_connection_count, bearer_token_count, active_connection, bearer_tokens = await _load_account_dashboard(
            account_id
        )
        if account is None:
            response = RedirectResponse(url="/login", status_code=303)
            clear_account_session_cookie(response)
            return response
        return HTMLResponse(
            _render_account_page(
                account,
                active_connection_count=active_connection_count,
                bearer_token_count=bearer_token_count,
                active_connection=active_connection,
                bearer_tokens=bearer_tokens,
                token_success="Bearer token issued successfully.",
                issued_raw_token=raw_token,
            )
        )
