# Этап 89. Security hot-fix — Sentry sanitizer + deploy defaults + landing URL

## Контекст

Baseline super-review 2026-04-17:
- F7 (high, security): `error_tracking.py::_sanitize_event` allowlist покрывает только `authorization`, `cookie`, `set-cookie`, `x-rest-api-key`, `x-api-key` — пропускает `x-user-token`, `x-vm-api-key`, `x-vm-domain`, `x-app-name`. Request body, cookies, extra context вообще не чистятся.
- B4 (blocker, docs): deploy-скрипты и `deploy-prod.yml` захардкодили `342915.simplecloud.ru` как дефолт — новый prod на `vetmanager-mcp.vromanichev.ru`.
- medium (docs): `landing_page.py`/`web_html.py` хардкодят `vetmanager-mcp.vromanichev.ru` в canonical/og:url — self-hosted получит неверный домен.

## Scope

1. Pattern-based sanitizer в Sentry (все заголовки с `token|key|secret|auth|api|cookie|bearer` в имени)
2. Cleanup request body, query params, cookies в Sentry событиях
3. Deploy-дефолт → `vetmanager-mcp.vromanichev.ru` во всех 4 скриптах + GHA workflow
4. `SITE_BASE_URL` env-переменная для landing canonical/og:url/mcp.json — дефолт `""` (placeholder в текстах для self-hosted ясности)
5. Тесты: assertion что заголовок `x-user-token` режется, query-param `api_key` режется, deploy-defaults обновлены

## Подзадачи

### 89.1 Sentry pattern-based sanitizer

`error_tracking.py`:
- Новая функция `_is_sensitive_key(name)` — lowercase substring match на паттерны
- `_sanitize_event` чистит: request.headers (как сейчас), request.cookies, request.query_string, request.data
- Сохранить безобидные `x-request-id`, `x-correlation-id` (они в паттерне matching — `request-id` не содержит токены, но имя может совпасть; добавить explicit allowlist)

LOC: ≤40.

### 89.2 Deploy defaults

Заменить `342915.simplecloud.ru` → `vetmanager-mcp.vromanichev.ru` в:
- `scripts/deploy_server.sh:12`
- `scripts/init_server.sh:14`
- `scripts/renew_cert_if_needed.sh:13`
- `scripts/sync_and_deploy_server.sh:11`
- `.github/workflows/deploy-prod.yml:67`

LOC: ≤10.

### 89.3 landing_page.py / web_html.py SITE_BASE_URL

- Env var `SITE_BASE_URL` (дефолт `"https://vetmanager-mcp.vromanichev.ru"` чтобы не сломать prod)
- `landing_page.py`: canonical, og:url, mcp.json url → f-string с SITE_BASE_URL
- `web_html.py`: mcp.json url

Если пусто — не подставлять эти поля / показать warning в self-hosted (минимальный impact, главное — вынести в env).

LOC: ≤20.

### 89.4 Тесты

- `test_sentry_sanitizer_redacts_x_user_token_header`
- `test_sentry_sanitizer_redacts_custom_secret_keys_via_pattern`
- `test_sentry_sanitizer_preserves_correlation_id`
- `test_deploy_scripts_use_correct_default_domain` (grep-style assertion — no legacy)
- `test_landing_page_uses_site_base_url_env` (monkeypatch env, assert canonical)

LOC: ≤80.

### 89.5 Codex review + commit + push

## Acceptance

- `test_sentry_sanitizer_*` зелёные
- Full suite зелёный
- Grep на `342915.simplecloud.ru` в репо возвращает 0 hits (кроме AssumptionLog упоминаний инцидента)
- Landing canonical управляется env'ом
