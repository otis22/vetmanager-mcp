"""HTML rendering helpers for the web UI."""

from __future__ import annotations

import os
from html import escape

from storage_models import Account, VetmanagerConnection
from tool_access_registry import (
    PRESET_DOCTOR,
    PRESET_FINANCE,
    PRESET_FRONTDESK,
    PRESET_FULL_ACCESS,
    PRESET_INVENTORY,
    PRESET_READ_ONLY,
    TOKEN_PRESET_LABELS,
)


_DEFAULT_SITE_BASE_URL = "https://vetmanager-mcp.vromanichev.ru"
_DOCTOR_PRESET_FORM_VALUE = "clinical_staff"


def _resolve_site_base_url() -> str:
    """Stage 100.5: same validation as landing_page._resolve_site_base_url —
    reject invalid operator input and fall back to prod default.
    """
    raw = (os.environ.get("SITE_BASE_URL") or _DEFAULT_SITE_BASE_URL).strip()
    raw = raw.rstrip("/")
    if not raw or len(raw) > 255:
        return _DEFAULT_SITE_BASE_URL
    if not (raw.startswith("http://") or raw.startswith("https://")):
        return _DEFAULT_SITE_BASE_URL
    if any(c in raw for c in ('"', "'", "<", ">", " ", "\t", "\n", "\r", "\x00")):
        return _DEFAULT_SITE_BASE_URL
    return raw
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
)
from vetmanager_connection_service import (
    INTEGRATION_HEALTH_ACTIVE,
    INTEGRATION_HEALTH_REAUTH_REQUIRED,
)
from web_security import CSRF_FIELD_NAME


def hidden_csrf_input(csrf_token: str) -> str:
    return f'<input type="hidden" name="{CSRF_FIELD_NAME}" value="{escape(csrf_token)}">'


def render_shell(title: str, body: str) -> str:
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
      padding: 24px;
      border-radius: 24px;
      border: 2px solid var(--accent);
      background: linear-gradient(180deg, rgba(187, 77, 36, 0.08), rgba(255,255,255,0.92));
      scroll-margin-top: 24px;
    }}
    .token-flash-warning {{
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 12px 16px;
      border-radius: 14px;
      background: rgba(187, 77, 36, 0.12);
      color: var(--accent-deep, #7d2d14);
      font-weight: 600;
      font-size: 0.95rem;
      margin-bottom: 16px;
    }}
    .token-flash-value {{
      display: block;
      width: 100%;
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.96);
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 0.88rem;
      line-height: 1.5;
      word-break: break-all;
      color: var(--ink);
      user-select: all;
    }}
    .copy-row {{
      display: flex;
      gap: 10px;
      align-items: center;
      margin-top: 12px;
    }}
    .copy-button {{
      white-space: nowrap;
      flex-shrink: 0;
    }}
    .copy-status {{
      min-height: 1.2em;
      margin-top: 10px;
      font-size: 0.92rem;
      color: #1f4b50;
    }}
    .token-flash-example {{
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 14px;
      background: rgba(29, 35, 33, 0.04);
      font-size: 0.85rem;
    }}
    .token-flash-example summary {{
      cursor: pointer;
      font-weight: 600;
      color: var(--ink);
    }}
    .token-flash-example pre {{
      margin: 10px 0 0;
      white-space: pre-wrap;
      word-break: break-all;
      font-size: 0.82rem;
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


def render_register_page(*, csrf_token: str, error: str | None = None, email: str = "") -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return render_shell(
        "Регистрация аккаунта",
        f"""
        <h1>Регистрация аккаунта</h1>
        <p>Создайте аккаунт сервиса для подключения клиники и выпуска Bearer-токенов.</p>
        {error_html}
        <form method="post" action="/register" data-testid="register-form">
          {hidden_csrf_input(csrf_token)}
          <label>Email
            <input type="email" name="email" autocomplete="email" value="{escape(email)}" required data-testid="register-email">
          </label>
          <label>Пароль
            <input type="password" name="password" autocomplete="new-password" minlength="8" required data-testid="register-password">
            <small style="color: var(--muted); font-size: 0.85rem;">Минимум 8 символов</small>
          </label>
          <button type="submit" data-testid="register-submit">Создать аккаунт</button>
        </form>
        <div class="actions">
          <a class="link" href="/login">Уже есть аккаунт</a>
          <a class="link" href="/">На лендинг</a>
        </div>
        """,
    )


def render_login_page(*, csrf_token: str, error: str | None = None, email: str = "") -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return render_shell(
        "Вход в аккаунт",
        f"""
        <h1>Вход в аккаунт</h1>
        <p>Войдите в аккаунт для управления интеграцией с Vetmanager и Bearer-токенами.</p>
        {error_html}
        <form method="post" action="/login" data-testid="login-form">
          {hidden_csrf_input(csrf_token)}
          <label>Email
            <input type="email" name="email" autocomplete="email" value="{escape(email)}" required data-testid="login-email">
          </label>
          <label>Пароль
            <input type="password" name="password" autocomplete="current-password" minlength="8" required data-testid="login-password">
          </label>
          <button type="submit" data-testid="login-submit">Войти</button>
        </form>
        <div class="actions">
          <a class="link" href="/register">Создать аккаунт</a>
          <a class="link" href="/">На лендинг</a>
        </div>
        """,
    )


def render_account_page(
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
    ip_mask: str = "*.*.*.*",
    token_access_preset: str = PRESET_FULL_ACCESS,
    token_is_depersonalized: bool = False,
    issued_token_access_label: str | None = None,
    issued_token_privacy_label: str | None = None,
) -> str:
    # Stage 100.6: escape even though _resolve_site_base_url validates —
    # defense-in-depth against future misconfig where validation may be
    # relaxed. html.escape is cheap and idempotent on safe strings.
    site_base_url = escape(_resolve_site_base_url())
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
    preset_options = "".join(
        (
            f'<option value="{escape(form_value)}" '
            f'{"selected" if token_access_preset == preset else ""}>'
            f"{escape(label)}</option>"
        )
        for form_value, preset, label in (
            (PRESET_FULL_ACCESS, PRESET_FULL_ACCESS, TOKEN_PRESET_LABELS[PRESET_FULL_ACCESS]),
            (PRESET_READ_ONLY, PRESET_READ_ONLY, TOKEN_PRESET_LABELS[PRESET_READ_ONLY]),
            (PRESET_FRONTDESK, PRESET_FRONTDESK, TOKEN_PRESET_LABELS[PRESET_FRONTDESK]),
            (_DOCTOR_PRESET_FORM_VALUE, PRESET_DOCTOR, TOKEN_PRESET_LABELS[PRESET_DOCTOR]),
            (PRESET_FINANCE, PRESET_FINANCE, TOKEN_PRESET_LABELS[PRESET_FINANCE]),
            (PRESET_INVENTORY, PRESET_INVENTORY, TOKEN_PRESET_LABELS[PRESET_INVENTORY]),
        )
    )
    issued_token_html = ""
    if issued_raw_token:
        issued_access_html = (
            f'<p><strong>Access:</strong> {escape(issued_token_access_label)}</p>'
            if issued_token_access_label
            else ""
        )
        issued_privacy_html = (
            f'<p><strong>Privacy:</strong> {escape(issued_token_privacy_label)}</p>'
            if issued_token_privacy_label
            else ""
        )
        issued_token_html = f"""
        <section class="token-flash" id="issued-token-panel">
          <h2 style="margin: 0 0 12px;">Новый Bearer-токен создан</h2>
          <div class="token-flash-warning">
            <span style="font-size: 1.2em;">&#9888;</span>
            <span>Токен показывается только один раз. После перезагрузки страницы он будет недоступен. Скопируйте его сейчас.</span>
          </div>
          <code class="token-flash-value" id="issued-token-value" data-testid="issued-token-value">{escape(issued_raw_token)}</code>
          <div class="copy-row">
            <button class="copy-button" id="issued-token-copy-button" type="button">Скопировать токен</button>
            <span class="copy-status" id="issued-token-copy-status" aria-live="polite"></span>
          </div>
          {issued_access_html}
          {issued_privacy_html}
          <details class="token-flash-example">
            <summary>Как подключить к Cursor / Claude Code</summary>
            <pre>{{
  "mcpServers": {{
    "vetmanager": {{
      "url": "{site_base_url}/mcp",
      "headers": {{
        "Authorization": "Bearer {escape(issued_raw_token)}"
      }}
    }}
  }}
}}</pre>
          </details>
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
                    f'{hidden_csrf_input(csrf_token)}'
                    '<button type="submit">Revoke</button>'
                    "</form>"
                )
            rows.append(
                "<tr>"
                f"<td>{escape(str(token['name']))}</td>"
                f"<td><code>{escape(str(token['token_prefix']))}</code></td>"
                f"<td>{escape(str(token.get('access_label', 'Legacy/custom')))}</td>"
                f"<td>{escape(str(token.get('privacy_label', 'Standard')))}</td>"
                f"<td><code>{escape(str(token['status']))}</code></td>"
                f"<td><code>{escape(str(token.get('ip_mask', '*.*.*.*')))}</code></td>"
                f"<td>{escape(str(token['expires_at']))}</td>"
                f"<td>{escape(str(token['last_used_at']))}</td>"
                f"<td>{escape(str(token['request_count']))}</td>"
                f"<td>{action_html}</td>"
                "</tr>"
            )
        token_list_html = (
            "<table>"
            "<thead><tr>"
            "<th>Name</th><th>Prefix</th><th>Access</th><th>Privacy</th><th>Status</th><th>IP mask</th><th>Expires</th><th>Last used</th><th>Requests</th><th>Actions</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    return render_shell(
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
        <hr style="border: none; border-top: 1px solid var(--line); margin: 28px 0;">
        <h2>Интеграция Vetmanager</h2>
        {error_html}
        {success_html}
        {active_connection_html}
        <form method="post" action="/account/integration" data-auth-wizard="true" data-testid="integration-form">
          {hidden_csrf_input(csrf_token)}
          <div class="panel-card">
            <strong>Выберите способ авторизации Vetmanager</strong>
            <p class="section-note">Сначала выберите удобный способ подключения. Мы покажем только нужные поля для следующего шага.</p>
            <div class="choice-grid">
              <label class="choice-option" id="auth-mode-domain-api-key">
                <span>
                  <input type="radio" name="auth_mode" value="{VETMANAGER_AUTH_MODE_DOMAIN_API_KEY}" {"checked" if show_domain_api_key_panel else ""} data-testid="auth-mode-domain-api-key-radio">
                  <strong>Подключить по API key</strong>
                </span>
                <p>Подходит, если у вас уже есть рабочий Vetmanager REST API key и нужно быстро подключить клинику.</p>
              </label>
              <label class="choice-option" id="auth-mode-user-token">
                <span>
                  <input type="radio" name="auth_mode" value="{VETMANAGER_AUTH_MODE_USER_TOKEN}" {"checked" if show_user_token_panel else ""} data-testid="auth-mode-user-token-radio">
                  <strong>Подключить по логину и паролю</strong>
                </span>
                <p>Используйте этот вариант, если сервис должен сам получить user token через login/password и дальше хранить только токен.</p>
              </label>
            </div>
          </div>
          <div class="panel-card field-panel" data-mode-panel="{VETMANAGER_AUTH_MODE_DOMAIN_API_KEY}" data-testid="panel-domain-api-key" {"hidden" if not show_domain_api_key_panel else ""}>
            <strong>Шаг 2. Данные клиники для API key</strong>
            <label>Clinic domain
              <input type="text" name="domain" value="{escape(domain_value)}" placeholder="myclinic" {domain_input_attrs} data-testid="integration-domain">
            </label>
            <label>Vetmanager REST API key
              <input type="password" name="api_key" autocomplete="off" placeholder="API key" {api_key_input_attrs} data-testid="integration-api-key">
            </label>
            <p class="hint">Этот вариант не требует логин и пароль пользователя Vetmanager. Достаточно домена клиники и REST API key.</p>
          </div>
          <div class="panel-card field-panel" data-mode-panel="{VETMANAGER_AUTH_MODE_USER_TOKEN}" data-testid="panel-user-token" {"hidden" if not show_user_token_panel else ""}>
            <strong>Шаг 2. Данные клиники для логина и пароля</strong>
            <label>Clinic domain
              <input type="text" name="domain" value="{escape(domain_value)}" placeholder="myclinic" {'' if show_user_token_panel else 'disabled'} data-panel-input="true" data-required-when-active="true" data-testid="integration-domain-user-token">
            </label>
            <label>Vetmanager login
              <input type="text" name="vm_login" value="{escape(form_vm_login)}" autocomplete="username" placeholder="user login" {login_input_attrs} data-testid="integration-vm-login">
            </label>
            <label>Vetmanager password
              <input type="password" name="vm_password" autocomplete="current-password" placeholder="password" {password_input_attrs} data-testid="integration-vm-password">
            </label>
            <p class="hint">Для этого режима сервис использует логин и пароль только для получения нового user token. Эти данные не сохраняются в storage, логи и audit trail.</p>
          </div>
          <div class="actions">
            <button type="submit" data-testid="integration-submit">Сохранить подключение</button>
            <button type="submit" formaction="/account/integration/reauth" data-testid="integration-reauth-submit">Переавторизоваться и обновить токен</button>
          </div>
        </form>
        <hr style="border: none; border-top: 1px solid var(--line); margin: 28px 0;">
        <h2>Выпуск Bearer-токенов</h2>
        {token_error_html}
        {token_success_html}
        {token_note}
        <form method="post" action="/account/tokens" data-testid="token-form">
          {hidden_csrf_input(csrf_token)}
          <label>Token name
            <input type="text" name="token_name" value="{escape(token_name)}" placeholder="Cursor production" required {token_disabled} data-testid="token-name">
          </label>
          <label>Expires in days
            <input type="number" name="expires_in_days" value="{escape(token_expiry_days)}" min="1" placeholder="30" {token_disabled} data-testid="token-expires-in-days">
          </label>
          <label>Access preset
            <select name="access_preset" {token_disabled} data-testid="token-access-preset">
              {preset_options}
            </select>
            <small style="color: var(--muted); font-size: 0.85rem;">Preset определяет scopes токена: без custom-конструктора и без per-tool ручной настройки.</small>
          </label>
          <label style="display: flex; gap: 10px; align-items: start;">
            <input type="checkbox" name="is_depersonalized" value="1" {"checked" if token_is_depersonalized else ""} {token_disabled} data-testid="token-is-depersonalized" style="width: auto; margin-top: 6px;">
            <span>
              <strong style="display: block; color: var(--ink);">Деперсонализировать ответы</strong>
              <small style="color: var(--muted); font-size: 0.85rem;">Скрывает ФИО, телефоны, email и адреса; позже этот токен будет использовать централизованный sanitizer ответа.</small>
            </span>
          </label>
          <label>Ограничение по IP
            <input type="text" name="ip_mask" value="{escape(ip_mask)}" placeholder="*.*.*.*" {token_disabled} data-testid="token-ip-mask">
            <small style="color: var(--muted); font-size: 0.85rem;">Маска IP: *.*.*.* — любой, 85.90.100.* — подсеть, 45.67.89.123 — точный IP</small>
          </label>
          <button type="submit" {token_disabled} data-testid="token-submit">Выпустить Bearer token</button>
        </form>
        <hr style="border: none; border-top: 1px solid var(--line); margin: 28px 0;">
        <h2>Текущие токены</h2>
        <p>В списке показываются только безопасные поля. Raw token после создания больше не доступен.</p>
        {token_list_html}
        <p>Текущий MCP runtime использует только <code>Authorization: Bearer &lt;service_token&gt;</code>. Этот web account уже стал источником регистрации, интеграции и выпуска токенов; следующим шагом здесь появится полноценный token list UI.</p>
        <form method="post" action="/logout" data-testid="logout-form">
          {hidden_csrf_input(csrf_token)}
          <button type="submit" data-testid="logout-submit">Выйти</button>
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
            const copyEl = document.getElementById('issued-token-value');
            const copyStatus = document.getElementById('issued-token-copy-status');
            if (copyButton && copyEl) {{
              copyButton.addEventListener('click', async () => {{
                try {{
                  await navigator.clipboard.writeText(copyEl.textContent);
                  if (copyStatus) copyStatus.textContent = 'Токен скопирован в буфер обмена.';
                }} catch (_error) {{
                  const range = document.createRange();
                  range.selectNodeContents(copyEl);
                  const sel = window.getSelection();
                  sel.removeAllRanges();
                  sel.addRange(range);
                  if (copyStatus) copyStatus.textContent = 'Автокопирование недоступно. Токен выделен, скопируйте вручную.';
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
