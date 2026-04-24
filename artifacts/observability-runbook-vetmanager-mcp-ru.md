# Runbook: observability и расследование инцидентов для vetmanager-mcp

> **Last updated:** stage 45 baseline. Метрики, добавленные после:
> - **Stage 88**: `vetmanager_upstream_requests_total{target,status}`, `vetmanager_upstream_request_latency_seconds_{count,sum,max}`, `vetmanager_tool_calls_total{endpoint,method,outcome}`, `vetmanager_tool_call_latency_seconds_*`.
> - **Stage 110**: `vetmanager_business_events_total{event=...}` — 4 lifecycle events (account_registered, web_login_succeeded, bearer_token_issued, bearer_token_revoked).
> - **Stage 111.1**: `/metrics` endpoint теперь требует `Authorization: Bearer $METRICS_AUTH_TOKEN` когда env задан (иначе 403). Без env — backward-compat open.
> - **Stage 112**: `circuit_breaker_opened` structured log на CLOSED→OPEN + HALF_OPEN→OPEN; `integration_save_failed` log + `vetmanager_auth_failures_total{source="web_integration[_reauth]"}`; `entity` вместо `url_path` в retry/timeout/network-error логах (privacy).
> - **Stage 134**: token audit committed logs пишутся только после successful DB commit и включают `request_id`/`correlation_id`; `/metrics` auth failures пишут security log + `vetmanager_auth_failures_total{source="metrics",reason="invalid_token"}`; custom web route 500/413 paths сохраняют correlation headers; billing host resolver coalesces concurrent cold-cache requests per domain.
>
> Полная ревизия runbook — отдельным этапом.

## 1. Быстрая проверка состояния

Минимальный smoke-check:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/readyz
curl -fsS http://localhost:8000/metrics | head -n 40
```

Если задан `METRICS_AUTH_TOKEN`, проверять `/metrics` нужно с bearer header:

```bash
curl -fsS -H "Authorization: Bearer $METRICS_AUTH_TOKEN" \
  http://localhost:8000/metrics | head -n 40
```

Ожидаемое поведение:
- `/healthz` отвечает `200` и `{"status":"ok","probe":"liveness",...}`
- `/readyz` отвечает `200`, если storage доступен
- `/metrics` отвечает plaintext в Prometheus-compatible формате; при заданном
  `METRICS_AUTH_TOKEN` запрос без корректного bearer получает `403`

Если `/healthz` не отвечает:
- процесс не запущен или недоступен по сети/reverse proxy
- сначала проверить контейнер и bind порта

Если `/readyz` отвечает `503`:
- проблема в storage access
- сначала проверить `DATABASE_URL`, доступность sqlite/postgres и права на файл/директорию

## 2. Что смотреть в логах

Ключевые поля логов:
- `request_id`
- `correlation_id`
- `event_category`
- `event_name`

Категории:
- `runtime` — host resolution, readiness/storage и runtime execution path
- `audit` — bearer token lifecycle и usage audit
- `security` — invalid CSRF, rate limiting и похожие события

Практика расследования:
- найти ошибку/аномалию по времени
- выделить `request_id` или `correlation_id`
- собрать всю цепочку событий по этому идентификатору
- проверить соседние `security`/`audit` events для той же временной зоны

## 3. Что смотреть в метриках

Базовые семейства:
- `vetmanager_http_requests_total`
- `vetmanager_http_request_latency_seconds_count`
- `vetmanager_http_request_latency_seconds_sum`
- `vetmanager_http_request_latency_seconds_max`
- `vetmanager_auth_failures_total`
- `vetmanager_upstream_failures_total`
- `vetmanager_token_preset_issued_total`
- `vetmanager_sanitizer_failures_total`

Типовые симптомы:
- рост `vetmanager_auth_failures_total{source="bearer_header",...}`
  обычно означает некорректный MCP client config
- рост `vetmanager_auth_failures_total{source="web_login",reason="invalid_credentials"}`
  может означать brute-force или пользовательские ошибки
- рост `vetmanager_auth_failures_total{source="metrics",reason="invalid_token"}`
  означает неверный или отсутствующий bearer для `/metrics` при заданном
  `METRICS_AUTH_TOKEN`; искать рядом `security` event `metrics_auth_failed`
- рост `vetmanager_upstream_failures_total{target="billing_api",...}`
  означает проблемы резолва Vetmanager host: timeout, network error,
  circuit-open или HTTP 5xx
- рост `vetmanager_upstream_failures_total{target="vetmanager_api",...}`
  означает timeout, network error, circuit-open или API 5xx со стороны
  Vetmanager; upstream HTTP 4xx смотрите в
  `vetmanager_upstream_requests_total{target="vetmanager_api",status="http_4xx"}`

## 4. Error tracking

Интеграция:
- backend: Sentry
- включается только при наличии `ERROR_TRACKING_DSN` или `SENTRY_DSN`
- sanitization hook редактирует чувствительные headers перед отправкой

Рекомендуемые production настройки:

```env
ERROR_TRACKING_DSN=https://<public>@o0.ingest.sentry.io/<project>
ERROR_TRACKING_ENVIRONMENT=production
ERROR_TRACKING_RELEASE=vetmanager-mcp@<release>
ERROR_TRACKING_TRACES_SAMPLE_RATE=0
```

Если Sentry пустой, а логи показывают ошибки:
- проверить, что DSN реально задан в runtime окружении контейнера
- убедиться, что bootstrap выполняется на старте процесса
- проверить исходящие сетевые ограничения до Sentry ingest

## 5. Типовые инциденты

### `/readyz` стал `503`

Действия:
- проверить `DATABASE_URL`
- проверить доступность БД и права на storage path
- посмотреть `runtime` event `storage_readiness_failed`

### Пользователь жалуется на `401` в MCP

Действия:
- проверить `Authorization: Bearer <service_token>` в MCP client config
- посмотреть `vetmanager_auth_failures_total`
- сверить audit events по bearer token lifecycle
- для token usage audit использовать только `token_audit_log_committed`;
  отсутствие такого event при failed transaction означает, что audit row не был
  durable committed

### В web UI растут ошибки входа

Действия:
- проверить `security` events по rate limiting
- проверить `web_login invalid_credentials`
- убедиться, что reverse proxy корректно передаёт client IP и настроен `WEB_TRUSTED_PROXY_IPS`

### Ошибки Vetmanager API

Действия:
- смотреть `vetmanager_upstream_failures_total` для timeout/network/circuit-open/5xx
- различать `billing_api` и `vetmanager_api`
- для 4xx смотреть `vetmanager_upstream_requests_total{status="http_4xx"}` и
  логи конкретного request/correlation id; 4xx обычно означает contract/input
  problem, а не degradation upstream

## 6. Связанные артефакты

- `artifacts/security-deployment-notes-vetmanager-mcp-ru.md`
- `artifacts/security-threat-model-vetmanager-mcp-ru.md`
- `PRD/этап-45-observability-and-monitoring.md`
