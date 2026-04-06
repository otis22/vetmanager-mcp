# PRD: Этап 59 — Рефакторинг web.py

## Цель
Разбить god-module web.py (1533 строк) на модули с чёткими границами.

## Архитектура после рефакторинга

### web.py (оркестратор, ~200 строк)
- `register_web_routes(mcp)` — вызывает sub-registrators
- Shared helpers: `_html_response`, `_redirect_response`, `_json_response`, etc.
- `_observed_custom_route`, `_apply_security_headers`
- `FormPayloadTooLarge`, `_read_form`, `_get_account_id_from_request`

### web_routes_system.py
- `/` (landing), `/healthz`, `/readyz`, `/metrics`

### web_routes_auth.py
- `/register GET/POST`, `/login GET/POST`, `/logout POST`

### web_routes_account.py
- `/account GET`, `/account/integration POST`, `/account/integration/reauth POST`
- `/account/tokens POST`, `/account/tokens/{id}/revoke POST`

### web_html.py
- `_render_shell`, `_render_register_page`, `_render_login_page`
- `_render_account_page`, `_load_account_dashboard`, `_render_account_dashboard_response`

## Принцип
- Все route-модули получают `mcp` и shared helpers через аргументы
- Тесты не меняются (public API — register_web_routes — остаётся)
- Каждый route-модуль экспортирует одну функцию: `register_*_routes(mcp, helpers)`
