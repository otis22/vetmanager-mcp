"""HTML rendering helpers for the web UI."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from html import escape

from observability_logging import RUNTIME_LOGGER
from storage_models import Account, VetmanagerConnection
from tool_access_registry import (
    PRESET_DOCTOR,
    PRESET_FINANCE,
    PRESET_FRONTDESK,
    PRESET_FULL_ACCESS,
    PRESET_INVENTORY,
    PRESET_READ_ONLY,
    PRESET_REPORT_AI,
    TOKEN_PRESET_SCOPES,
    get_token_preset_label,
)
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
)
from vetmanager_connection_service import (
    INTEGRATION_HEALTH_ACTIVE,
    INTEGRATION_HEALTH_REAUTH_REQUIRED,
)
from web_security import CSRF_FIELD_NAME

# Stage 210 (K-3): display-only labels for the cabinet, which clinic staff read.
# `TOKEN_PRESET_LABELS` stays English on purpose — it is embedded in MCP
# scope-denied messages addressed to an AI agent, not to a person.
TOKEN_PRESET_DISPLAY_LABELS: dict[str, str] = {
    PRESET_FULL_ACCESS: "Полный доступ",
    PRESET_READ_ONLY: "Только чтение",
    PRESET_FRONTDESK: "Регистратура",
    PRESET_DOCTOR: "Врач",
    PRESET_FINANCE: "Финансы",
    PRESET_INVENTORY: "Склад",
    PRESET_REPORT_AI: "Аналитика",
}

# Stage 210 (K-4): the status column was the most important field and the only
# one with no visual signal — all three states shared one grey pill.
TOKEN_STATUS_DISPLAY: dict[str, str] = {
    "active": "Работает",
    "expired": "Истёк",
    "revoked": "Отозван",
}


def display_access_label(inferred_preset: str | None) -> str:
    """Russian access label for the cabinet.

    Deliberately separate from `get_token_preset_label`, whose English labels go
    into MCP scope-denied messages read by an AI agent rather than by a person.
    """
    if inferred_preset is None:
        return "Настроен вручную"
    return TOKEN_PRESET_DISPLAY_LABELS.get(
        inferred_preset, get_token_preset_label(inferred_preset)
    )


def _account_status_display(status: str) -> str:
    """Stage 210 (K-3): account status is prose for a clinic, not an enum dump."""
    return {
        "active": "активен",
        "blocked": "заблокирован",
        "pending": "ожидает подтверждения",
    }.get(str(status), str(status))


def _timestamp_html(iso_value: str | None, fallback_text: str) -> str:
    """Render a timestamp the client can localise.

    Stage 210 (K-7): the attribute carries machine time, the element carries the
    server-rendered UTC string. Without JS the user sees exactly what they saw
    before, so the localisation is an enhancement rather than a dependency.
    """
    if not iso_value:
        return escape(str(fallback_text))
    return (
        f'<time datetime="{escape(str(iso_value))}" data-local-time>'
        f"{escape(str(fallback_text))}</time>"
    )


_DEFAULT_SITE_BASE_URL = "https://vetmanager-mcp.vromanichev.ru"
_DOCTOR_PRESET_FORM_VALUE = "clinical_staff"
_CHATGPT_OAUTH_ACCESS_PRESETS = (
    PRESET_REPORT_AI,
    PRESET_READ_ONLY,
    PRESET_FRONTDESK,
    PRESET_FULL_ACCESS,
)
_CHATGPT_OAUTH_PRESET_COPY = {
    PRESET_REPORT_AI: (
        "Аналитик",
        "всё чтение + работа с отчётами",
    ),
    PRESET_READ_ONLY: (
        "Только чтение",
        "можно смотреть данные, нельзя менять",
    ),
    PRESET_FRONTDESK: (
        "Регистратура",
        "расписание, клиенты, питомцы и сообщения",
    ),
    PRESET_FULL_ACCESS: (
        "Полный доступ",
        "чтение и изменение всех доступных данных",
    ),
}


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


def _resolve_mcp_path() -> str:
    raw = (os.environ.get("MCP_PATH") or "/mcp").strip()
    if not raw or len(raw) > 128:
        return "/mcp"
    if not raw.startswith("/"):
        return "/mcp"
    if any(c in raw for c in ('"', "'", "<", ">", " ", "\t", "\n", "\r", "\x00")):
        return "/mcp"
    return raw


def _activation_datetime(value: object, fallback: object = None) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(fallback, str):
        text = fallback.strip()
        if not text or text in {"Never", "No expiry"}:
            return None
        if text.endswith(" UTC"):
            text = text.removesuffix(" UTC")
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _activation_token_is_usable(token: dict[str, object], *, now: datetime) -> bool:
    if str(token.get("status")) != "active":
        return False
    expires_at = _activation_datetime(token.get("expires_at_raw"), token.get("expires_at"))
    return expires_at is None or expires_at > now


def _activation_token_has_client_usage(token: dict[str, object]) -> bool:
    try:
        if int(token.get("request_count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        RUNTIME_LOGGER.warning(
            "activation request_count parse failed",
            extra={
                "event_name": "activation_request_count_parse_failed",
                "token_id": token.get("id"),
            },
        )
    last_used_at = _activation_datetime(token.get("last_used_at_raw"), token.get("last_used_at"))
    return last_used_at is not None


def compute_activation_state(
    *,
    active_connection: VetmanagerConnection | None,
    integration_health_status: str,
    bearer_tokens: list[dict[str, object]],
    now: datetime | None = None,
) -> str:
    """Stage 197.4: activation funnel state shared by page render and polling.

    Returns one of: needs_connection / needs_token / needs_client_use / ready.
    """
    now = now or datetime.now(timezone.utc)
    integration_ready = (
        active_connection is not None
        and integration_health_status == INTEGRATION_HEALTH_ACTIVE
    )
    if not integration_ready:
        return "needs_connection"
    has_active_token = any(
        _activation_token_is_usable(token, now=now) for token in bearer_tokens
    )
    if not has_active_token:
        return "needs_token"
    has_client_usage = any(
        _activation_token_is_usable(token, now=now)
        and _activation_token_has_client_usage(token)
        for token in bearer_tokens
    )
    if not has_client_usage:
        return "needs_client_use"
    return "ready"


# Stage 197.2: defaults for the one-click token issuance panel.
QUICK_TOKEN_NAME = "Мой первый токен"

_ACTIVATION_STEPPER = {
    "needs_connection": "Шаг 1 из 3 — Подключите Vetmanager",
    "needs_token": "Шаг 2 из 3 — Выпустите ключ доступа",
    "needs_client_use": "Шаг 3 из 3 — Подключите MCP-клиент",
}


def hidden_csrf_input(csrf_token: str) -> str:
    return f'<input type="hidden" name="{CSRF_FIELD_NAME}" value="{escape(csrf_token)}">'


def render_shell(title: str, body: str, *, main_class: str = "card") -> str:
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
      --danger: #9c3d1c;
      --danger-line: #d9b3a6;
      --warn-bg: #f6ecd6;
      --warn-ink: #7d5808;
      --ok-bg: #dcece0;
      --ok-ink: #2c5f3a;
      --off-bg: #e7eaec;
      --off-ink: #5f6d78;
      --font-body: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, "Helvetica Neue", Arial, sans-serif;
      --font-display: "Iowan Old Style", "Source Serif Pro", "Charter", "Cambria", Georgia, serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(47, 109, 115, 0.15), transparent 34%),
        linear-gradient(180deg, #faf5ea 0%, var(--bg) 100%);
      color: var(--ink);
      font-family: var(--font-body);
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
    .account-card {{
      width: min(1040px, 100%);
    }}
    h1 {{
      margin: 0 0 14px;
      font: 700 clamp(2.2rem, 5vw, 3.4rem)/0.95 var(--font-display);
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
    label {{ display: block; }}
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
      background: rgba(255, 255, 255, 0.72);
      color: var(--ink);
      border: 1px solid var(--line);
    }}
    button.primary {{
      background: var(--accent);
      color: #fff9f3;
      border-color: var(--accent);
    }}
    button.danger {{
      background: transparent;
      color: var(--danger);
      border: 1px solid var(--danger-line);
    }}
    button.danger:hover,
    button.danger:focus-visible {{
      background: var(--danger);
      color: #fff9f3;
      border-color: var(--danger);
    }}
    .link {{
      color: var(--ink);
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.55);
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 12px;
      margin-top: 18px;
    }}
    .actions form {{ margin: 0; }}
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
    .choice-option:has(input:checked) {{
      border-color: var(--accent);
      box-shadow: 0 0 0 1px var(--accent);
      background: rgba(187, 77, 36, 0.06);
    }}
    button:disabled {{
      opacity: 0.5;
      cursor: not-allowed;
    }}
    input:disabled, select:disabled {{
      opacity: 0.6;
      cursor: not-allowed;
    }}
    .stepper {{
      display: inline-block;
      margin: 0 0 12px;
      padding: 6px 14px;
      border-radius: 999px;
      border: 1px solid var(--accent);
      color: var(--accent);
      font-weight: 700;
      font-size: 0.95rem;
    }}
    .form-status {{
      min-height: 1.2em;
      color: var(--muted);
      font-size: 0.95rem;
      align-self: center;
    }}
    .reveal-row {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .reveal-row input {{
      flex: 1;
      min-width: 0;
    }}
    .reveal-toggle {{
      padding: 10px 14px;
      font-size: 0.9rem;
      flex-shrink: 0;
    }}
    .section-block {{
      margin-top: 26px;
      border-top: 1px solid var(--line);
      padding-top: 16px;
    }}
    .section-block > summary {{
      cursor: pointer;
      list-style: none;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 4px 0;
    }}
    .section-block > summary::-webkit-details-marker {{ display: none; }}
    .section-block > summary::after {{
      content: "";
      margin-left: auto;
      width: 9px;
      height: 9px;
      border-right: 2px solid var(--muted);
      border-bottom: 2px solid var(--muted);
      transform: rotate(45deg) translate(-2px, -2px);
      transition: transform 200ms ease;
      flex-shrink: 0;
    }}
    .section-block[open] > summary::after {{
      transform: rotate(-135deg) translate(-2px, -2px);
      border-color: var(--accent);
    }}
    .section-block > summary h2 {{
      display: inline-block;
      margin: 0;
      vertical-align: middle;
    }}
    .section-block > summary .summary-hint {{
      margin-left: 10px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .waiting-indicator {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 12px;
      color: #1f4b50;
      font-weight: 600;
    }}
    .waiting-indicator::before {{
      content: "";
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
      animation: waiting-pulse 1.6s ease-in-out infinite;
      flex-shrink: 0;
    }}
    @keyframes waiting-pulse {{
      0%, 100% {{ opacity: 0.25; }}
      50% {{ opacity: 1; }}
    }}
    .client-guide details {{
      margin-top: 10px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255,255,255,0.7);
    }}
    .client-guide summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--ink);
    }}
    .client-guide pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    .card {{
      min-width: 0;
    }}
    .choice-option {{ cursor: pointer; }}
    .choice-option input {{
      width: 20px;
      height: 20px;
      margin-right: 8px;
      accent-color: var(--accent);
      flex-shrink: 0;
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
      flex-wrap: wrap;
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
    .metric > strong {{
      display: block;
      font-size: 1.8rem;
      color: var(--ink);
    }}
    .section-note {{
      margin-top: 8px;
      color: var(--muted);
    }}
    .activation-status {{
      margin-top: 18px;
      padding: 18px;
      border-radius: 22px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.76);
    }}
    .activation-status h2 {{
      margin: 0 0 8px;
      font-size: 1.25rem;
      line-height: 1.25;
    }}
    .activation-status ul {{
      margin: 12px 0 0;
      padding-left: 1.35rem;
      list-style: none;
    }}
    .activation-status li {{
      margin: 6px 0;
    }}
    .activation-done {{
      color: #1f4b50;
      font-weight: 700;
    }}
    .activation-next {{
      color: #7d2d14;
      font-weight: 700;
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
    .token-table {{
      table-layout: fixed;
    }}
    .token-table th,
    .token-table td {{
      overflow-wrap: anywhere;
    }}
    .token-cell {{
      min-width: 0;
    }}
    .token-name {{
      display: block;
      font-weight: 700;
      color: var(--ink);
      overflow-wrap: anywhere;
    }}
    .token-prefix {{
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-size: 0.86rem;
    }}
    .token-status {{
      display: inline-block;
      padding: 2px 9px;
      border-radius: 999px;
      background: var(--off-bg);
      color: var(--off-ink);
      font-size: 0.82rem;
      font-weight: 700;
      white-space: nowrap;
    }}
    .status-active {{ background: var(--ok-bg); color: var(--ok-ink); }}
    .status-expired {{ background: var(--off-bg); color: var(--off-ink); }}
    .status-revoked {{ background: rgba(156, 61, 28, 0.12); color: var(--danger); }}
    .badge-in-use {{
      display: inline-block;
      margin-left: 6px;
      padding: 2px 8px;
      border-radius: 999px;
      background: var(--ok-bg);
      color: var(--ok-ink);
      font-size: 0.76rem;
      font-weight: 700;
      white-space: nowrap;
    }}
    .warning {{
      margin-top: 8px;
      padding: 10px 12px;
      border-radius: 12px;
      background: var(--warn-bg);
      color: var(--warn-ink);
      font-size: 0.92rem;
      line-height: 1.45;
    }}
    /* A record now spans up to three rows: data, details, warning. The
       separator belongs after the last of them, otherwise the details block
       reads as part of the next record. */
    .note-row td, .detail-row td {{
      padding-top: 0;
      border-bottom: 1px solid var(--line);
    }}
    .token-table tbody tr:has(+ .detail-row) > td {{ border-bottom: 0; }}
    .token-table .detail-row:has(+ .note-row) > td {{ border-bottom: 0; }}
    .token-archive {{
      margin-top: 18px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .token-archive > summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--muted);
      list-style: none;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 0;
    }}
    .token-archive > summary::-webkit-details-marker {{ display: none; }}
    .token-archive > summary::after {{
      content: "";
      width: 8px;
      height: 8px;
      border-right: 2px solid currentColor;
      border-bottom: 2px solid currentColor;
      transform: rotate(45deg) translate(-2px, -2px);
      transition: transform 200ms ease;
    }}
    .token-archive[open] > summary::after {{
      transform: rotate(-135deg) translate(-2px, -2px);
    }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .account-topbar {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 22px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--line);
    }}
    .account-topbar .seal {{
      width: 38px;
      height: 38px;
      border-radius: 11px;
      background: #1e3a4d;
      color: #f5f5f0;
      display: grid;
      place-items: center;
      font-weight: 700;
      font-size: 0.86rem;
      letter-spacing: -0.02em;
      flex-shrink: 0;
    }}
    .account-topbar .who {{
      margin-left: auto;
      color: var(--muted);
      font-size: 0.9rem;
      word-break: break-word;
    }}
    .account-topbar strong {{ font-size: 0.98rem; }}
    .token-details {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .token-details summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--muted);
    }}
    .token-details dl {{
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      gap: 4px 10px;
      margin: 8px 0 0;
    }}
    .token-details dt {{
      color: var(--muted);
      font-weight: 700;
    }}
    .token-details dd {{
      margin: 0;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .token-action-cell {{
      text-align: right;
    }}
    .token-action-cell form {{
      display: inline-flex;
      margin: 0;
    }}
    .token-action-cell button {{
      padding: 10px 16px;
      white-space: nowrap;
    }}
    @media (max-width: 780px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .choice-grid {{ grid-template-columns: 1fr; }}
      .copy-row {{ grid-template-columns: 1fr; }}
      .token-table,
      .token-table thead,
      .token-table tbody,
      .token-table tr,
      .token-table th,
      .token-table td {{
        display: block;
      }}
      .token-table thead {{
        display: none;
      }}
      .token-table tr {{
        padding: 12px 0;
        border-bottom: 1px solid var(--line);
      }}
      .token-table td {{
        display: flex;
        justify-content: space-between;
        gap: 18px;
        padding: 8px 0;
        border-bottom: 0;
      }}
      .token-table td::before {{
        content: attr(data-label);
        flex: 0 0 34%;
        color: var(--muted);
        font-weight: 700;
      }}
      .token-table td.token-cell {{
        display: block;
      }}
      .token-table td.token-cell::before {{
        display: block;
        margin-bottom: 4px;
      }}
      .token-action-cell {{
        text-align: left;
      }}
      .token-table td.grant-name-cell {{
        display: block;
      }}
      .token-table td.grant-name-cell::before {{
        display: block;
        margin-bottom: 4px;
      }}
      .token-table .detail-row td,
      .token-table .note-row td {{
        display: block;
        padding: 4px 0 10px;
      }}
      .token-table .detail-row td::before,
      .token-table .note-row td::before {{
        content: none;
      }}
      .token-action-cell form {{
        justify-content: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <main class="{escape(main_class)}">{body}</main>
</body>
</html>"""


def render_register_page(
    *, csrf_token: str, error: str | None = None, email: str = "", selected_agent: str = ""
) -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    agent_html = f'<input type="hidden" name="agent" value="{escape(selected_agent)}">' if selected_agent else ""
    return render_shell(
        "Регистрация аккаунта",
        f"""
        <h1>Регистрация аккаунта</h1>
        <p>Аккаунт нужен, чтобы подключить клинику и выдать помощнику доступ. Занимает пару минут.</p>
        {error_html}
        <form method="post" action="/register" data-testid="register-form">
          {hidden_csrf_input(csrf_token)}
          {agent_html}
          <label>Email
            <input type="email" name="email" autocomplete="email" value="{escape(email)}" required data-testid="register-email">
          </label>
          <label>Пароль
            <input type="password" name="password" autocomplete="new-password" minlength="8" required data-testid="register-password">
            <small style="color: var(--muted); font-size: 0.85rem;">Минимум 8 символов</small>
          </label>
          <button type="submit" class="primary" data-testid="register-submit">Создать аккаунт</button>
        </form>
        <div class="actions">
          <a class="link" href="/login">Уже есть аккаунт</a>
          <a class="link" href="/">На лендинг</a>
        </div>
        """,
    )


def render_login_page(
    *,
    csrf_token: str,
    error: str | None = None,
    email: str = "",
    next_url: str = "",
) -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    next_html = f'<input type="hidden" name="next" value="{escape(next_url)}">' if next_url else ""
    return render_shell(
        "Вход в аккаунт",
        f"""
        <h1>Вход в аккаунт</h1>
        <p>Войдите, чтобы управлять подключением клиники и ключами доступа.</p>
        {error_html}
        <form method="post" action="/login" data-testid="login-form">
          {hidden_csrf_input(csrf_token)}
          {next_html}
          <label>Email
            <input type="email" name="email" autocomplete="email" value="{escape(email)}" required data-testid="login-email">
          </label>
          <label>Пароль
            <input type="password" name="password" autocomplete="current-password" minlength="8" required data-testid="login-password">
          </label>
          <button type="submit" class="primary" data-testid="login-submit">Войти</button>
        </form>
        <div class="actions">
          <a class="link" href="/register">Создать аккаунт</a>
          <a class="link" href="/">На лендинг</a>
        </div>
        """,
    )


def render_oauth_consent_page(
    *,
    csrf_token: str,
    request_state: str,
    client_name: str,
    scopes: list[str],
    connections: list[dict[str, str | int]],
    script_nonce: str,
    error: str | None = None,
    selected_access_preset: str = PRESET_REPORT_AI,
    selected_privacy_mode: str = "depersonalized",
) -> str:
    client_display_name = client_name.strip() or "помощник"
    consent_title = f"Доступ для {client_display_name}" if client_name.strip() else "Доступ для помощника"
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    scope_items = "".join(f"<li><code>{escape(scope)}</code></li>" for scope in scopes) or "<li>не переданы</li>"
    access_options = "".join(
        (
            f'<option value="{escape(preset)}" {"selected" if selected_access_preset == preset else ""}>'
            f'{escape(_CHATGPT_OAUTH_PRESET_COPY[preset][0])}</option>'
        )
        for preset in _CHATGPT_OAUTH_ACCESS_PRESETS
    )
    effective_preview_rows = []
    granted_scope_rows = []
    for preset in _CHATGPT_OAUTH_ACCESS_PRESETS:
        title, description = _CHATGPT_OAUTH_PRESET_COPY[preset]
        effective_preview_rows.append(
            "<li>"
            f"<strong>{escape(title)}:</strong> {escape(description)}"
            "</li>"
        )
        scopes_text = " ".join(TOKEN_PRESET_SCOPES[preset])
        granted_scope_rows.append(
            "<li>"
            f"<strong>{escape(title)}:</strong> <code>{escape(scopes_text)}</code>"
            "</li>"
        )
    effective_preview_html = "".join(effective_preview_rows)
    granted_scopes_html = "".join(granted_scope_rows)
    depersonalized_checked = "checked" if selected_privacy_mode != "personal_data" else ""
    personal_data_checked = "checked" if selected_privacy_mode == "personal_data" else ""
    if len(connections) == 1:
        connection = connections[0]
        connection_input = (
            f'<input type="hidden" name="connection_id" value="{escape(str(connection["id"]))}">'
            f'<p>Клиника: <code>{escape(str(connection.get("domain", "n/a")))}</code></p>'
        )
    else:
        options = "".join(
            f'<option value="{escape(str(connection["id"]))}">{escape(str(connection.get("domain", "n/a")))}</option>'
            for connection in connections
        )
        connection_input = f"""
          <label>Подключение Vetmanager
            <select name="connection_id" required>
              {options}
            </select>
          </label>
        """
    return render_shell(
        consent_title,
        f"""
        <h1>{escape(consent_title)}</h1>
        <p><strong>{escape(client_display_name)}</strong> просит доступ к данным Vetmanager.</p>
        {error_html}
        <section class="metric" data-testid="oauth-effective-scope-preview">
          <span>Что означают уровни доступа</span>
          <ul>{effective_preview_html}</ul>
        </section>
        <section class="metric" data-testid="oauth-requested-scopes-technical" style="font-size: 0.72rem; color: var(--muted);">
          <span>Технические scopes, которые передал {escape(client_display_name)}</span>
          <ul>{scope_items}</ul>
        </section>
        <details class="metric" data-testid="oauth-granted-scopes-technical" style="font-size: 0.72rem; color: var(--muted);">
          <summary>Технические scopes, которые выдаёт каждый уровень</summary>
          <ul>{granted_scopes_html}</ul>
        </details>
        <form method="post" action="/oauth/authorize/consent" data-testid="oauth-consent-form">
          {hidden_csrf_input(csrf_token)}
          <input type="hidden" name="request_state" value="{escape(request_state)}">
          {connection_input}
          <label>Уровень доступа
            <select name="access_preset" required data-testid="oauth-access-preset">
              {access_options}
            </select>
            <small style="color: var(--muted); font-size: 0.85rem;">{escape(client_display_name)} получит права выбранного уровня; это может быть больше технического запроса клиента. Полный доступ требует отдельного подтверждения.</small>
            <small style="display: block; color: var(--muted); font-size: 0.85rem;">Если выбрать уровень шире технического запроса, будут выданы права выбранного уровня.</small>
          </label>
          <fieldset class="metric" style="border: 1px solid var(--line); margin: 16px 0;" data-testid="oauth-privacy-mode">
            <legend>Персональные данные</legend>
            <label style="display: flex; gap: 10px; align-items: start;">
              <input type="radio" name="privacy_mode" value="depersonalized" {depersonalized_checked} data-testid="oauth-privacy-depersonalized" style="width: auto; margin-top: 6px;">
              <span>
                <strong style="display: block; color: var(--ink);">Без персональных данных</strong>
                <small style="color: var(--muted); font-size: 0.85rem;">ФИО, телефоны, email и адреса будут скрыты в ответах помощника.</small>
              </span>
            </label>
            <label style="display: flex; gap: 10px; align-items: start;">
              <input type="radio" name="privacy_mode" value="personal_data" {personal_data_checked} data-testid="oauth-privacy-personal-data" style="width: auto; margin-top: 6px;">
              <span>
                <strong style="display: block; color: var(--ink);">Разрешить персональные данные</strong>
                <small style="color: var(--muted); font-size: 0.85rem;">{escape(client_display_name)} сможет видеть имена клиентов, телефоны, email и похожие поля, если выбранные права разрешают такой tool call.</small>
              </span>
            </label>
          </fieldset>
          <label id="oauth-confirm-full-access-row" style="display: flex; gap: 10px; align-items: start;" hidden>
              <input type="checkbox" name="confirm_full_access" value="1" data-testid="oauth-confirm-full-access" style="width: auto; margin-top: 6px;">
            <span>
              <strong style="display: block; color: var(--ink);">Подтвердить полный доступ</strong>
              <small style="color: var(--muted); font-size: 0.85rem;">Нужно только для полного доступа.</small>
            </span>
          </label>
          <button type="submit" class="primary">Разрешить</button>
        </form>
        <script nonce="{escape(script_nonce)}">
          (() => {{
            const preset = document.querySelector('[data-testid="oauth-access-preset"]');
            const confirmation = document.querySelector('[data-testid="oauth-confirm-full-access"]');
            const confirmationRow = document.getElementById('oauth-confirm-full-access-row');
            const syncFullAccessConfirmation = () => {{
              const requiresConfirmation = preset.value === '{PRESET_FULL_ACCESS}';
              confirmationRow.hidden = !requiresConfirmation;
              if (!requiresConfirmation) confirmation.checked = false;
            }};
            preset.addEventListener('change', syncFullAccessConfirmation);
            syncFullAccessConfirmation();
          }})();
        </script>
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
    bearer_tokens: list[dict[str, object]],
    oauth_grants: list[dict[str, object]],
    integration_error: str | None = None,
    integration_success: str | None = None,
    form_auth_mode: str = VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    form_domain: str = "",
    form_vm_login: str = "",
    token_error: str | None = None,
    token_success: str | None = None,
    issued_raw_token: str | None = None,
    token_name: str = "",
    token_expiry_days: str = "30",
    ip_mask: str = "",
    token_access_preset: str = PRESET_REPORT_AI,
    token_is_depersonalized: bool = False,
    issued_token_access_label: str | None = None,
    issued_token_privacy_label: str | None = None,
    activation_now: datetime | None = None,
    selected_agent: str = "",
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
          <p>После регистрации шаг один: выбрать способ входа, подключить клинику и только потом выпустить ключ доступа для помощника.</p>
        </div>
        """
    active_connection_html = """
        <p>Vetmanager ещё не подключён. Ключ доступа можно выпустить, но помощник пока не сможет получить данные клиники.</p>
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
    # Stage 196.3: alerts are announced to screen readers and auto-scrolled
    # into view after the full-page POST re-render — on mobile the form sits
    # deep in the page and an unscrolled error is effectively invisible.
    error_html = (
        f'<div class="error" id="integration-error" role="alert" data-autoscroll="true">{escape(integration_error)}</div>'
        if integration_error
        else ""
    )
    success_html = (
        '<div class="success" id="integration-success" role="status" data-autoscroll="true">{}'
        ' <a class="link" href="#token-section" data-testid="integration-success-cta">Выпустить ключ доступа</a></div>'.format(
            escape(integration_success)
        )
        if integration_success
        else ""
    )
    token_error_html = (
        f'<div class="error" role="alert" data-autoscroll="true">{escape(token_error)}</div>'
        if token_error
        else ""
    )
    token_success_html = (
        '<div class="success" role="status">{}</div>'.format(escape(token_success))
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
            (PRESET_REPORT_AI, PRESET_REPORT_AI, TOKEN_PRESET_DISPLAY_LABELS[PRESET_REPORT_AI]),
            (PRESET_FULL_ACCESS, PRESET_FULL_ACCESS, TOKEN_PRESET_DISPLAY_LABELS[PRESET_FULL_ACCESS]),
            (PRESET_READ_ONLY, PRESET_READ_ONLY, TOKEN_PRESET_DISPLAY_LABELS[PRESET_READ_ONLY]),
            (PRESET_FRONTDESK, PRESET_FRONTDESK, TOKEN_PRESET_DISPLAY_LABELS[PRESET_FRONTDESK]),
            (_DOCTOR_PRESET_FORM_VALUE, PRESET_DOCTOR, TOKEN_PRESET_DISPLAY_LABELS[PRESET_DOCTOR]),
            (PRESET_FINANCE, PRESET_FINANCE, TOKEN_PRESET_DISPLAY_LABELS[PRESET_FINANCE]),
            (PRESET_INVENTORY, PRESET_INVENTORY, TOKEN_PRESET_DISPLAY_LABELS[PRESET_INVENTORY]),
        )
    )
    issued_token_html = ""
    if issued_raw_token:
        issued_access_html = (
            f'<p><strong>Уровень доступа:</strong> {escape(issued_token_access_label)}</p>'
            if issued_token_access_label
            else ""
        )
        issued_privacy_html = (
            f'<p><strong>Персональные данные:</strong> {escape(issued_token_privacy_label)}</p>'
            if issued_token_privacy_label
            else ""
        )
        issued_token_html = f"""
        <section class="token-flash" id="issued-token-panel">
          <h2 style="margin: 0 0 12px;">Ключ доступа создан</h2>
          <div class="token-flash-warning">
            <span style="font-size: 1.2em;">&#9888;</span>
            <span>Токен показывается только один раз. После перезагрузки страницы он будет недоступен. Скопируйте его сейчас.</span>
          </div>
          <code class="token-flash-value" id="issued-token-value" data-testid="issued-token-value">{escape(issued_raw_token)}</code>
          <div class="copy-row">
            <button class="copy-button" id="issued-token-copy-button" type="button" data-copy-source="issued-token-value" data-copy-kind="token" data-copy-status="issued-token-copy-status" data-copied-text="Токен скопирован в буфер обмена.">Скопировать токен</button>
            <button class="copy-button link" id="issued-config-copy-button" type="button" data-copy-source="issued-token-config" data-copy-kind="config" data-copy-status="issued-token-copy-status" data-copied-text="Готовый конфиг скопирован — вставьте его в настройки MCP клиента.">Скопировать готовый конфиг</button>
            <span class="copy-status" id="issued-token-copy-status" aria-live="polite"></span>
          </div>
          {issued_access_html}
          {issued_privacy_html}
          <details class="token-flash-example" open data-testid="issued-token-instructions">
            <summary>Как подключить к Cursor / Claude Code</summary>
            <pre id="issued-token-config">{{
  "mcpServers": {{
    "vetmanager": {{
      "url": "{site_base_url}{escape(_resolve_mcp_path())}",
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
    chatgpt_mcp_url = f"{site_base_url}{_resolve_mcp_path()}"
    token_note = (
        "<p>Сначала подключите Vetmanager, затем можно выпустить ключ доступа.</p>"
        if active_connection is None
        else (
            "<p>Сначала восстановите подключение к Vetmanager, затем можно выпустить ключ доступа.</p>"
            if integration_health_status != INTEGRATION_HEALTH_ACTIVE
            else "<p>После создания raw token показывается только один раз, а в storage сохраняется только hash и безопасный prefix.</p>"
        )
    )
    activation_now = activation_now or datetime.now(timezone.utc)
    integration_ready = active_connection is not None and integration_health_status == INTEGRATION_HEALTH_ACTIVE
    has_active_token = any(
        _activation_token_is_usable(token, now=activation_now)
        for token in bearer_tokens
    )
    has_client_usage = any(
        _activation_token_is_usable(token, now=activation_now)
        and _activation_token_has_client_usage(token)
        for token in bearer_tokens
    )
    has_chatgpt = any(str(grant.get("status")) == "active" for grant in oauth_grants)
    selected_agent_label = {"chatgpt": "ChatGPT", "claude": "Claude", "manus": "Manus"}.get(selected_agent, "")
    selected_agent_html = (
        f"<p>Вы выбрали {escape(selected_agent_label)}. Сначала подключите клинику.</p>"
        if selected_agent_label
        else ""
    )
    oauth_success_html = ""
    if has_chatgpt and integration_ready and not has_client_usage:
        oauth_success_html = """
        <section class="panel-card" data-testid="oauth-first-request-guide">
          <strong>Подсказки для вашего помощника</strong>
          <p>Откройте помощника и попробуйте одну из фраз:</p>
          <ul>
            <li>Покажи записи на сегодня</li>
            <li>Найди карточку клиента по фамилии</li>
            <li>Сколько приёмов было на прошлой неделе?</li>
            <li>Кого напомнить о визите завтра?</li>
            <li>Кто не приходил больше полугода?</li>
          </ul>
        </section>
        """
    activation_state = compute_activation_state(
        active_connection=active_connection,
        integration_health_status=integration_health_status,
        bearer_tokens=bearer_tokens,
        now=activation_now,
    )
    if activation_state == "needs_connection":
        activation_title = "Подключите Vetmanager"
        activation_summary = "Сначала сохраните рабочую интеграцию клиники."
    elif activation_state == "needs_token":
        activation_title = "Выпустите ключ доступа"
        activation_summary = "Интеграция готова; следующий шаг — выдать токен для MCP-клиента."
    elif activation_state == "needs_client_use":
        activation_title = "Подключите MCP-клиент"
        activation_summary = "Токен готов; вставьте MCP URL и Authorization bearer token в клиент."
    else:
        activation_title = "Готово к работе"
        activation_summary = "Интеграция и токен уже используются MCP-клиентом."
    # Stage 199.2: compact stepper under the page title while activation is
    # in progress; disappears once the account is fully ready.
    stepper_html = ""
    if activation_state in _ACTIVATION_STEPPER:
        stepper_html = (
            f'<p class="stepper" data-testid="activation-stepper">'
            f"{escape(_ACTIVATION_STEPPER[activation_state])}</p>"
        )
    # Stage 197.4: live waiting indicator — the page polls activation status
    # and reloads once the first MCP request lands.
    waiting_html = ""
    if activation_state == "needs_client_use":
        waiting_html = (
            '<p class="waiting-indicator" data-testid="activation-waiting" '
            f'data-poll-activation="{activation_state}">'
            "Ждём первый запрос от MCP-клиента… страница обновится автоматически.</p>"
        )

    def _activation_item(done: bool, text: str, *, current: bool = False) -> str:
        marker_class = "activation-done" if done else ("activation-next" if current else "")
        marker = "✓" if done else ("следующий шаг" if current else "ожидает")
        return (
            f'<li><span class="{marker_class}">{escape(marker)}</span> '
            f"{escape(text)}</li>"
        )

    activation_html = f"""
        <section class="activation-status" data-testid="activation-status" data-activation-state="{activation_state}">
          <h2>{escape(activation_title)}</h2>
          <p>{escape(activation_summary)}</p>
          <ul>
            {_activation_item(integration_ready, "Vetmanager подключён", current=activation_state == "needs_connection")}
            {_activation_item(has_active_token, "Ключ доступа выпущен", current=activation_state == "needs_token")}
            {_activation_item(has_client_usage, "Помощник сделал первый запрос", current=activation_state == "needs_client_use")}
            {_activation_item(has_chatgpt, "ChatGPT подключён", current=False)}
          </ul>
          {waiting_html}
        </section>
    """
    def _token_row(token: dict) -> str:
        status = str(token["status"])
        action_html = "&mdash;"
        if status == "active":
            action_html = (
                f'<form method="post" action="/account/tokens/{token["id"]}/revoke">'
                f'{hidden_csrf_input(csrf_token)}'
                '<button type="submit" class="danger" '
                f'data-confirm="Отозвать ключ «{escape(str(token["name"]))}»? '
                'Помощник, который им пользуется, потеряет доступ.">Отозвать</button>'
                "</form>"
            )
        token_name_html = f"""
                <span class="token-name">{escape(str(token['name']))}</span>
                <code class="token-prefix">{escape(str(token['token_prefix']))}</code>
                <details class="token-details">
                  <summary>Подробнее</summary>
                  <dl>
                    <dt>Данные</dt>
                    <dd>{escape(str(token.get('privacy_label', 'Обычные данные')))}</dd>
                    <dt>Разрешённые адреса</dt>
                    <dd><code>{escape(str(token.get('ip_mask', '*.*.*.*')))}</code></dd>
                    <dt>Действует до</dt>
                    <dd>{_timestamp_html(token.get('expires_at_raw'), token['expires_at'])}</dd>
                  </dl>
                </details>
            """
        return (
            "<tr>"
            f'<td class="token-cell" data-label="Ключ">{token_name_html}</td>'
            f'<td data-label="Доступ">{escape(str(token.get("access_label", "Настроен вручную")))}</td>'
            f'<td data-label="Статус"><span class="token-status status-{escape(status)}">'
            f'{escape(TOKEN_STATUS_DISPLAY.get(status, status))}</span></td>'
            f'<td data-label="Последнее использование">'
            f'{_timestamp_html(token.get("last_used_at_raw"), token["last_used_at"])}</td>'
            f'<td data-label="Запросов">{escape(str(token["request_count"]))}</td>'
            f'<td class="token-action-cell" data-label="Действия">{action_html}</td>'
            "</tr>"
        )

    def _token_table(tokens: list[dict], testid: str) -> str:
        return (
            f'<table class="token-table" data-testid="{testid}">'
            '<colgroup><col style="width: 31%;"><col style="width: 16%;"><col style="width: 11%;"><col style="width: 17%;"><col style="width: 10%;"><col style="width: 15%;"></colgroup>'
            "<thead><tr>"
            "<th>Ключ</th><th>Доступ</th><th>Статус</th><th>Последнее использование</th>"
            "<th>Запросов</th><th><span class=\"sr-only\">Действия</span></th>"
            "</tr></thead>"
            f"<tbody>{''.join(_token_row(token) for token in tokens)}</tbody>"
            "</table>"
        )

    # Stage 210 (K-4): 9 of 13 rows were expired or revoked and took 70% of the
    # section, so finished keys fold away behind a counter.
    token_list_html = "<p>Ключей пока нет.</p>"
    working_tokens = [t for t in bearer_tokens if str(t["status"]) == "active"]
    finished_tokens = [t for t in bearer_tokens if str(t["status"]) != "active"]
    if bearer_tokens:
        parts = []
        if working_tokens:
            parts.append(_token_table(working_tokens, "token-list"))
        else:
            parts.append('<p data-testid="token-list">Рабочих ключей нет.</p>')
        if finished_tokens:
            parts.append(
                '<details class="token-archive" data-testid="finished-tokens">'
                f"<summary>Завершённые ключи · {len(finished_tokens)}</summary>"
                f'{_token_table(finished_tokens, "finished-token-list")}'
                "</details>"
            )
        token_list_html = "".join(parts)
    oauth_grants_html = "<p>Подключений ChatGPT пока нет.</p>"
    if oauth_grants:
        rows = []
        for grant in oauth_grants:
            status = str(grant["status"])
            client_name = str(grant["client_name"])
            action_html = "&mdash;"
            if status == "active":
                action_html = (
                    f'<form method="post" action="/account/oauth-grants/{grant["id"]}/revoke">'
                    f'{hidden_csrf_input(csrf_token)}'
                    '<button type="submit" class="danger" '
                    f'data-confirm="Отключить {escape(client_name)}? '
                    'Помощник перестанет отвечать по данным клиники, пока вы не подключите его заново.">'
                    "Отключить</button>"
                    "</form>"
                )
            in_use_html = (
                ' <span class="badge-in-use">Используется сейчас</span>'
                if grant.get("is_last_used")
                else ""
            )
            # Stage 210 (K-2): these used to render inside a ~78px column and
            # broke mid-word. They are warnings, not errors, and get a full row.
            notes = []
            if grant.get("legacy_full_access"):
                notes.append(
                    "Подключение выдано с полным доступом. Отключите и подключите "
                    f"{escape(client_name)} заново, чтобы выбрать уровень доступа явно."
                )
            if grant.get("legacy_privacy"):
                notes.append(
                    "Подключение создано в старом режиме, персональные данные сейчас скрыты. "
                    f"Отключите и подключите {escape(client_name)} заново, чтобы выбрать режим явно."
                )
            rows.append(
                "<tr>"
                f'<td class="grant-name-cell" data-label="Помощник">{escape(client_name)}{in_use_html}</td>'
                f'<td data-label="Доступ">{escape(str(grant.get("access_label", "Настроен вручную")))}</td>'
                f'<td data-label="Персональные данные">{escape(str(grant.get("privacy_label", "Скрыты")))}</td>'
                f'<td data-label="Статус"><span class="token-status status-{escape(status)}">'
                f'{escape(TOKEN_STATUS_DISPLAY.get(status, status))}</span></td>'
                f'<td data-label="Подключено">'
                f'{_timestamp_html(grant.get("created_at_raw"), grant["created_at"])}</td>'
                f'<td data-label="Последнее использование">'
                f'{_timestamp_html(grant.get("last_used_at_raw"), grant["last_used_at"])}</td>'
                f'<td class="token-action-cell" data-label="Действия">{action_html}</td>'
                "</tr>"
                f'<tr class="detail-row"><td colspan="7">'
                '<details class="token-details"><summary>Подробнее</summary>'
                "<dl><dt>Разрешённые действия</dt>"
                f'<dd><code>{escape(str(grant.get("scope_summary", "нет")))}</code></dd></dl>'
                "</details></td></tr>"
                + (
                    f'<tr class="note-row"><td colspan="7">'
                    + "".join(f'<div class="warning">{note}</div>' for note in notes)
                    + "</td></tr>"
                    if notes
                    else ""
                )
            )
        oauth_grants_html = (
            '<table class="token-table" data-testid="oauth-grant-list">'
            "<thead><tr>"
            "<th>Помощник</th><th>Доступ</th><th>Персональные данные</th><th>Статус</th>"
            "<th>Подключено</th><th>Последнее использование</th>"
            "<th><span class=\"sr-only\">Действия</span></th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    # Stage 196.6: re-auth is meaningless before the first save — show the
    # second submit button only when the saved user token actually went stale.
    reauth_button_html = ""
    if integration_health_status == INTEGRATION_HEALTH_REAUTH_REQUIRED:
        reauth_button_html = (
            '<button type="submit" formaction="/account/integration/reauth" '
            'data-testid="integration-reauth-submit">Переавторизоваться и обновить токен</button>'
        )
    # Stage 199.2: activation-first layout — each big section is a <details>
    # that opens only when it is the current funnel step or carries a message.
    integration_open = "open" if (
        activation_state == "needs_connection"
        or integration_error is not None
        or integration_success is not None
        or integration_health_status == INTEGRATION_HEALTH_REAUTH_REQUIRED
    ) else ""
    token_section_open = "open" if (
        activation_state == "needs_token"
        or token_error is not None
        or token_success is not None
        or issued_raw_token is not None
    ) else ""
    tokens_list_open = "open" if bearer_tokens else ""
    chatgpt_open = "open" if (activation_state == "ready" or oauth_grants) else ""
    meta_open = "open" if activation_state == "ready" else ""
    integration_summary_hint = (
        "активна" if integration_ready
        else ("требуется повторная авторизация" if integration_health_status == INTEGRATION_HEALTH_REAUTH_REQUIRED else "не настроена")
    )
    # Stage 197.2: one-click issuance with explicit IP-scope choice. Choosing
    # "any" is the wildcard confirmation (stage-155 contract stays explicit).
    quick_issue_html = ""
    if activation_state == "needs_token":
        quick_issue_html = f"""
          <div class="panel-card" id="token-quick" data-testid="token-quick-issue">
            <strong>Быстрый старт: токен с рекомендуемыми настройками</strong>
            <p class="section-note">Доступ Analytics (отчёты без персональных данных), срок 30 дней, имя «{escape(QUICK_TOKEN_NAME)}».</p>
            <form method="post" action="/account/tokens" data-submit-lock="Выпускаем токен…" data-testid="token-quick-form">
              {hidden_csrf_input(csrf_token)}
              <input type="hidden" name="token_name" value="{escape(QUICK_TOKEN_NAME)}">
              <input type="hidden" name="expires_in_days" value="30">
              <input type="hidden" name="access_preset" value="{PRESET_REPORT_AI}">
              <div class="choice-grid">
                <label class="choice-option">
                  <span>
                    <input type="radio" name="quick_ip_choice" value="any" checked data-testid="token-quick-ip-any">
                    <strong>Работать с любого IP</strong>
                  </span>
                  <p>Подходит для ChatGPT, облачных клиентов и работы из разных сетей. Доступ защищает сам токен — храните его как пароль.</p>
                </label>
                <label class="choice-option">
                  <span>
                    <input type="radio" name="quick_ip_choice" value="current" data-testid="token-quick-ip-current">
                    <strong>Только мой текущий IP</strong>
                  </span>
                  <p>Строже, но токен перестанет работать при смене сети или IP-адреса (мобильный интернет, домашний роутер).</p>
                </label>
              </div>
              <div class="actions">
                <button type="submit" class="primary" data-testid="token-quick-submit">Выпустить ключ доступа</button>
                <span class="form-status" data-submit-status aria-live="polite"></span>
              </div>
            </form>
            <p class="hint">Нужны другие права, срок или IP-маска — раскройте «Выпустить Bearer-токен вручную» ниже.</p>
          </div>
        """
    manual_form_open = "" if (quick_issue_html and token_error is None) else "open"
    # Stage 197.3: when the token exists but no client used it yet, the
    # connect instructions become the primary content instead of a collapsed
    # afterthought.
    client_instructions_html = ""
    if activation_state == "needs_client_use":
        chatgpt_mcp_url_html = escape(chatgpt_mcp_url)
        config_placeholder = (
            "{\n"
            '  "mcpServers": {\n'
            '    "vetmanager": {\n'
            f'      "url": "{chatgpt_mcp_url_html}",\n'
            '      "headers": {\n'
            '        "Authorization": "Bearer &lt;ВАШ_ТОКЕН&gt;"\n'
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        client_instructions_html = f"""
        <section class="panel-card client-guide" id="client-connect" data-testid="client-connect-instructions">
          <strong>Почти готово — спросите помощника</strong>
          <p>Откройте ChatGPT, Claude или Manus и попробуйте одну из фраз:</p>
          <ul>
            <li>Покажи записи на сегодня</li>
            <li>Найди карточку клиента по фамилии</li>
            <li>Сколько приёмов было на прошлой неделе?</li>
            <li>Кого напомнить о визите завтра?</li>
            <li>Кто не приходил больше полугода?</li>
          </ul>
          <details>
            <summary>Для разработчиков</summary>
            <p>Адрес подключения: <code>{chatgpt_mcp_url_html}</code>. Если токен не сохранился, выпустите новый ниже.</p>
          <details open>
            <summary>Cursor / Claude Code</summary>
            <p>Добавьте блок в конфигурацию MCP (Cursor: <code>mcp.json</code>; Claude Code: <code>claude mcp add</code> или <code>.mcp.json</code>) и подставьте свой токен:</p>
            <pre>{config_placeholder}</pre>
          </details>
          <details>
            <summary>ChatGPT</summary>
            <p>Для ChatGPT ключ доступа не нужен — он подключается сам. Раскройте секцию «Подключения ChatGPT» ниже и следуйте инструкции.</p>
          </details>
          </details>
        </section>
        """
    return render_shell(
        "Кабинет аккаунта",
        f"""
        <header class="account-topbar">
          <div class="seal" aria-label="Vetmanager">VM</div>
          <div>
            <strong>ИИ-помощник для Vetmanager</strong>
          </div>
          <span class="who">{escape(account.email)}</span>
        </header>
        <h1>Мой помощник</h1>
        {stepper_html}
        <p>Подключите Vetmanager — и помощник сможет отвечать на вопросы о вашей клинике.</p>
        <div class="grid" data-testid="account-summary">
          <section class="metric">
            <span>Статус аккаунта</span>
            <strong>{escape(_account_status_display(account.status))}</strong>
          </section>
          <section class="metric">
            <span>Активные подключения</span>
            <strong>{active_connection_count}</strong>
          </section>
          <section class="metric">
            <span>Ключи доступа</span>
            <strong>{bearer_token_count}</strong>
          </section>
        </div>
        {selected_agent_html}
        {issued_token_html}
        {activation_html}
        {oauth_success_html}
        {client_instructions_html}
        {onboarding_html}
        <details class="section-block" id="account-meta" data-testid="account-meta" {meta_open}>
          <summary><h2>Аккаунт и данные</h2></summary>
          <div class="metric">
            <span>Что мы храним</span>
            <p>Сервис не хранит данные вашей клиники. Сохраняются только настройки подключения и служебные сведения о ключах доступа — без них помощник не сможет авторизоваться.</p>
            <p>Логин и пароль Vetmanager не сохраняются: они нужны только один раз, чтобы получить ключ подключения. Если вы смените пароль в Vetmanager, ключ может перестать работать — тогда потребуется подключиться заново.</p>
          </div>

        </details>
        <details class="section-block" id="integration-section" data-testid="integration-section" {integration_open}>
        <summary><h2>Интеграция Vetmanager</h2><span class="summary-hint">{escape(integration_summary_hint)}</span></summary>
        {error_html}
        {success_html}
        {active_connection_html}
        <form method="post" action="/account/integration" data-auth-wizard="true" data-submit-lock="Проверяем подключение к Vetmanager… это может занять до минуты." data-testid="integration-form">
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
            <p class="hint" data-testid="vetmanager-api-key-help">В Vetmanager откройте Настройки -> Интеграция с сервисами, включите REST API, нажмите редактирование и скопируйте API KEY. Этот ключ даёт широкий доступ к программе, поэтому вставляйте его только здесь и не отправляйте в чат.</p>
            <label>Домен клиники
              <input type="text" name="domain" value="{escape(domain_value)}" placeholder="myclinic" autocapitalize="none" autocorrect="off" spellcheck="false" {domain_input_attrs} data-testid="integration-domain">
              <small style="color: var(--muted); font-size: 0.85rem;">Только поддомен: для myclinic.vetmanager.ru — myclinic. Можно вставить полный адрес, мы возьмём из него поддомен.</small>
            </label>
            <label>Ключ Vetmanager REST API
              <span class="reveal-row">
                <input type="password" id="integration-api-key-input" name="api_key" autocomplete="off" placeholder="API key" autocapitalize="none" spellcheck="false" {api_key_input_attrs} data-testid="integration-api-key">
                <button type="button" class="link reveal-toggle" data-reveal-target="integration-api-key-input" aria-pressed="false" data-testid="integration-api-key-reveal">Показать</button>
              </span>
            </label>
            <p class="hint">Этот вариант не требует логин и пароль пользователя Vetmanager. Достаточно домена клиники и REST API key.</p>
          </div>
          <div class="panel-card field-panel" data-mode-panel="{VETMANAGER_AUTH_MODE_USER_TOKEN}" data-testid="panel-user-token" {"hidden" if not show_user_token_panel else ""}>
            <strong>Шаг 2. Данные клиники для логина и пароля</strong>
            <label>Домен клиники
              <input type="text" name="domain" value="{escape(domain_value)}" placeholder="myclinic" autocapitalize="none" autocorrect="off" spellcheck="false" {'' if show_user_token_panel else 'disabled'} data-panel-input="true" data-required-when-active="true" data-testid="integration-domain-user-token">
              <small style="color: var(--muted); font-size: 0.85rem;">Только поддомен: для myclinic.vetmanager.ru — myclinic. Можно вставить полный адрес, мы возьмём из него поддомен.</small>
            </label>
            <label>Vetmanager login
              <input type="text" name="vm_login" value="{escape(form_vm_login)}" autocomplete="username" placeholder="user login" autocapitalize="none" autocorrect="off" spellcheck="false" {login_input_attrs} data-testid="integration-vm-login">
            </label>
            <label>Vetmanager password
              <input type="password" name="vm_password" autocomplete="current-password" placeholder="password" {password_input_attrs} data-testid="integration-vm-password">
            </label>
            <p class="hint">Для этого режима сервис использует логин и пароль только для получения нового user token. Эти данные не сохраняются в storage, логи и audit trail.</p>
          </div>
          <div class="actions">
            <button type="submit" class="primary" data-testid="integration-submit">Сохранить подключение</button>
            {reauth_button_html}
            <span class="form-status" data-submit-status aria-live="polite"></span>
          </div>
        </form>
        </details>
        <details class="section-block" id="token-section" data-testid="token-section" {token_section_open}>
        <summary><h2>Выпуск ключей доступа</h2></summary>
        {token_error_html}
        {token_success_html}
        {token_note}
        {quick_issue_html}
        <details class="panel-card" data-testid="token-manual-form" {manual_form_open}>
        <summary>Выпустить Bearer-токен вручную</summary>
        <form method="post" action="/account/tokens" data-submit-lock="Выпускаем токен…" data-testid="token-form">
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
            <small style="color: var(--muted); font-size: 0.85rem;">Уровень доступа определяет, что помощник сможет видеть. Настройка по отдельным действиям не требуется.</small>
          </label>
          <label style="display: flex; gap: 10px; align-items: start;">
            <input type="checkbox" name="is_depersonalized" value="1" {"checked" if token_is_depersonalized else ""} {token_disabled} data-testid="token-is-depersonalized" style="width: auto; margin-top: 6px;">
            <span>
              <strong style="display: block; color: var(--ink);">Деперсонализировать ответы</strong>
              <small style="color: var(--muted); font-size: 0.85rem;">Скрывает ФИО, телефоны, email и адреса; позже этот токен будет использовать централизованный sanitizer ответа.</small>
            </span>
          </label>
          <label>Ограничение по IP
            <input type="text" name="ip_mask" value="{escape(ip_mask)}" placeholder="45.67.89.123" {token_disabled} data-testid="token-ip-mask">
            <small style="color: var(--muted); font-size: 0.85rem;">Необязательно. Оставьте пустым для любого IP; 45.67.89.123 — точный IP, 85.90.100.* — подсеть.</small>
          </label>
          <label style="display: flex; gap: 10px; align-items: start;">
            <input type="checkbox" name="confirm_full_access" value="1" {token_disabled} data-testid="token-confirm-full-access" style="width: auto; margin-top: 6px;">
            <span>
              <strong style="display: block; color: var(--ink);">Подтвердить полный доступ</strong>
              <small style="color: var(--muted); font-size: 0.85rem;">Нужно только для полного доступа.</small>
            </span>
          </label>
          <div class="actions">
            <button type="submit" class="primary" {token_disabled} data-testid="token-submit">Выпустить ключ доступа</button>
            <span class="form-status" data-submit-status aria-live="polite"></span>
          </div>
        </form>
        </details>
        </details>
        <details class="section-block" id="tokens-list-section" data-testid="tokens-list-section" {tokens_list_open}>
        <summary><h2>Текущие ключи доступа</h2></summary>
        <p>В списке видны только безопасные сведения. Сам ключ показывается один раз — сразу после создания.</p>
        {token_list_html}
        </details>
        <details class="section-block" id="mcp-data-section" data-testid="mcp-data-section" open>
          <summary><h2>Данные MCP</h2></summary>
          <p>Это единый адрес подключения для всех помощников, поддерживающих MCP с OAuth.</p>
          <code class="token-flash-value" id="mcp-url" data-testid="mcp-url">{escape(chatgpt_mcp_url)}</code>
          <div class="copy-row">
            <button class="copy-button" id="mcp-copy-button" type="button" data-copy-source="mcp-url" data-copy-kind="mcp_url" data-copy-status="mcp-copy-status" data-copied-text="URL скопирован в буфер обмена.">Скопировать URL</button>
            <span class="copy-status" id="mcp-copy-status" aria-live="polite"></span>
          </div>
        </details>
        <details class="section-block" id="claude-section" data-testid="claude-connect-instructions" open>
          <summary><h2>Подключение Claude</h2></summary>
          <ol>
            <li>Нажмите на профиль и откройте Settings.</li>
            <li>Откройте Connectors и выберите Add custom connector.</li>
            <li>Вставьте URL ниже и нажмите Connect.</li>
            <li>Откроется вход в этот кабинет и выбор уровня доступа.</li>
          </ol>
          <code class="token-flash-value" id="claude-mcp-url" data-testid="claude-mcp-url">{escape(chatgpt_mcp_url)}</code>
          <div class="copy-row">
            <button class="copy-button" id="claude-mcp-copy-button" type="button" data-copy-source="claude-mcp-url" data-copy-kind="mcp_url" data-copy-status="claude-mcp-copy-status" data-copied-text="URL скопирован в буфер обмена.">Скопировать URL</button>
            <span class="copy-status" id="claude-mcp-copy-status" aria-live="polite"></span>
          </div>
        </details>
        <details class="section-block" id="chatgpt-section" data-testid="chatgpt-section" {chatgpt_open}>
        <summary><h2>Подключения ChatGPT</h2></summary>
        <div class="panel-card" data-testid="chatgpt-connect-instructions">
          <strong>Подключение ChatGPT</strong>
          <p>Пока сервис не опубликован в ChatGPT Plugin directory, подключение делается вручную как developer-mode plugin/app.</p>
          <ol>
            <li>Откройте ChatGPT web.</li>
            <li>Нажмите на своё имя или аватар в левом нижнем углу и откройте Settings.</li>
            <li>Включите Developer mode. Обычно он находится в Security and login; в workspace-планах админ может включать его в Apps или Connected Data settings.</li>
            <li>Откройте Settings → Plugins или перейдите на <code>chatgpt.com/plugins</code>.</li>
            <li>Нажмите + или Create и добавьте plugin/app с MCP Server URL ниже.</li>
            <li>Если ChatGPT покажет Scan Tools — запустите проверку tools, затем сохраните draft или создайте plugin.</li>
            <li>При OAuth-входе ChatGPT откроет этот кабинет; войдите и выберите уровень доступа.</li>
            <li>В новом чате нажмите + рядом с полем ввода, откройте More и выберите созданный plugin/app.</li>
          </ol>
          <p>Ключ доступа копировать не нужно: ChatGPT подключается сам, а права вы выберете на экране подтверждения.</p>
          <code class="token-flash-value" id="chatgpt-mcp-url" data-testid="chatgpt-mcp-url">{escape(chatgpt_mcp_url)}</code>
          <div class="copy-row">
            <button class="copy-button" id="chatgpt-mcp-copy-button" type="button" data-copy-source="chatgpt-mcp-url" data-copy-kind="mcp_url" data-copy-status="chatgpt-mcp-copy-status" data-copied-text="URL скопирован в буфер обмена.">Скопировать URL</button>
            <span class="copy-status" id="chatgpt-mcp-copy-status" aria-live="polite"></span>
          </div>
          <p class="hint">По умолчанию помощник получает аналитику без персональных данных — этого хватает для отчётов. Полный доступ и персональные данные нужно выбирать отдельно и явно.</p>
        </div>
        {oauth_grants_html}
        </details>
        <details class="section-block" id="mcp-universal-section" data-testid="mcp-universal-instructions">
          <summary><h2>Другие помощники</h2></summary>
          <p>Для Manus и других клиентов используйте тот же URL: добавьте его как custom MCP connector с OAuth.</p>
        </details>
        <div class="actions">
          <a class="link" href="/">На лендинг</a>
          <form method="post" action="/logout" data-testid="logout-form">
            {hidden_csrf_input(csrf_token)}
            <button type="submit" data-testid="logout-submit">Выйти из аккаунта</button>
          </form>
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

            // Stage 210 (K-1): revoking a key or disconnecting an assistant is
            // irreversible and used to fire on the first click.
            for (const button of document.querySelectorAll('button[data-confirm]')) {{
              button.addEventListener('click', (event) => {{
                if (!window.confirm(button.getAttribute('data-confirm'))) {{
                  event.preventDefault();
                  event.stopPropagation();
                }}
              }});
            }}

            // Stage 210 (K-7): UTC is three hours off for a Moscow clinic. The
            // server text stays as the fallback when Intl is unavailable.
            if (window.Intl && typeof Intl.DateTimeFormat === 'function') {{
              const localTime = new Intl.DateTimeFormat('ru-RU', {{
                day: 'numeric', month: 'short', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
              }});
              for (const node of document.querySelectorAll('time[data-local-time]')) {{
                const parsed = new Date(node.getAttribute('datetime'));
                if (!Number.isNaN(parsed.getTime())) {{
                  node.title = node.textContent.trim();
                  node.textContent = localTime.format(parsed);
                }}
              }}
            }}

            // Stage 196.5: lock submit buttons and show progress while the
            // server probes Vetmanager — prevents mobile double-submits.
            for (const form of document.querySelectorAll('form[data-submit-lock]')) {{
              form.addEventListener('submit', () => {{
                const status = form.querySelector('[data-submit-status]');
                if (status) status.textContent = form.getAttribute('data-submit-lock');
                for (const button of form.querySelectorAll('button[type="submit"]')) {{
                  button.disabled = true;
                }}
              }});
            }}

            // Stage 196.5: show/hide toggle for the pasted API key.
            for (const toggle of document.querySelectorAll('[data-reveal-target]')) {{
              toggle.addEventListener('click', () => {{
                const input = document.getElementById(toggle.getAttribute('data-reveal-target'));
                if (!input) return;
                const reveal = input.type === 'password';
                input.type = reveal ? 'text' : 'password';
                toggle.textContent = reveal ? 'Скрыть' : 'Показать';
                toggle.setAttribute('aria-pressed', reveal ? 'true' : 'false');
              }});
            }}

            // Stage 197.3: aggregate copy telemetry (no secrets in payload).
            const csrfInput = document.querySelector('input[name="{CSRF_FIELD_NAME}"]');
            const reportCopy = (kind) => {{
              if (!csrfInput) return;
              const body = new URLSearchParams();
              body.set('{CSRF_FIELD_NAME}', csrfInput.value);
              body.set('kind', kind);
              fetch('/account/telemetry/token-copied', {{
                method: 'POST',
                body,
                headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
              }}).catch(() => {{}});
            }};

            for (const button of document.querySelectorAll('[data-copy-source]')) {{
              button.addEventListener('click', async () => {{
                const source = document.getElementById(button.getAttribute('data-copy-source'));
                const status = document.getElementById(button.getAttribute('data-copy-status'));
                if (!source) return;
                try {{
                  await navigator.clipboard.writeText(source.textContent);
                  if (status) status.textContent = button.getAttribute('data-copied-text') || 'Скопировано.';
                }} catch (_error) {{
                  const range = document.createRange();
                  range.selectNodeContents(source);
                  const sel = window.getSelection();
                  sel.removeAllRanges();
                  sel.addRange(range);
                  if (status) status.textContent = 'Автокопирование недоступно. Значение выделено, скопируйте вручную.';
                }}
                reportCopy(button.getAttribute('data-copy-kind') || 'unknown');
              }});
            }}

            // Stage 199.2: anchor links open the target <details> section.
            const openAncestors = (el) => {{
              let node = el.tagName === 'DETAILS' ? el : el.closest('details');
              while (node) {{
                node.open = true;
                node = node.parentElement ? node.parentElement.closest('details') : null;
              }}
            }};
            const openForHash = (hash) => {{
              if (!hash || hash.length < 2) return;
              let target = null;
              try {{ target = document.querySelector(hash); }} catch (_error) {{ return; }}
              if (target) openAncestors(target);
            }};
            document.addEventListener('click', (event) => {{
              const link = event.target.closest('a[href^="#"]');
              if (link) openForHash(link.getAttribute('href'));
            }});
            openForHash(location.hash);

            // Stage 196.3: after a full-page POST re-render the browser lands
            // at the top; bring the freshest alert (or issued token) into view.
            const issuedPanel = document.getElementById('issued-token-panel');
            const scrollTarget = issuedPanel || document.querySelector('[data-autoscroll="true"]');
            if (scrollTarget) {{
              openAncestors(scrollTarget);
              scrollTarget.scrollIntoView({{ behavior: 'auto', block: 'start' }});
            }}

            // Stage 197.4: poll activation status while waiting for the first
            // MCP request; reload once the state advances.
            const pollEl = document.querySelector('[data-poll-activation]');
            if (pollEl) {{
              const initialState = pollEl.getAttribute('data-poll-activation');
              const forcedReloadKey = 'vm_activation_forced_reload_count';
              const pollAttemptKey = 'vm_activation_poll_attempt_count';
              let forcedReloads = Number(sessionStorage.getItem(forcedReloadKey) || '0');
              let pollAttempts = Number(sessionStorage.getItem(pollAttemptKey) || '0');
              const reloadAfterAttempts = 20;
              const maxPollAttempts = 80;
              const timer = setInterval(async () => {{
                try {{
                  pollAttempts += 1;
                  sessionStorage.setItem(pollAttemptKey, String(pollAttempts));
                  const response = await fetch('/account/activation-status', {{
                    headers: {{ 'Accept': 'application/json' }},
                  }});
                  if (!response.ok) return;
                  const payload = await response.json();
                  if (payload.state && payload.state !== initialState) {{
                    sessionStorage.removeItem(forcedReloadKey);
                    sessionStorage.removeItem(pollAttemptKey);
                    clearInterval(timer);
                    location.reload();
                  }}
                  if (pollAttempts >= reloadAfterAttempts) {{
                    if (forcedReloads < 1) {{
                      forcedReloads += 1;
                      sessionStorage.setItem(forcedReloadKey, String(forcedReloads));
                      clearInterval(timer);
                      location.reload();
                    }}
                  }}
                  if (pollAttempts >= maxPollAttempts) {{
                    clearInterval(timer);
                  }}
                }} catch (_error) {{}}
              }}, 15000);
            }}
          }})();
        </script>
        """,
        main_class="card account-card",
    )
