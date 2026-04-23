# Этап 134. Reliability and observability hardening

## Контекст

Источник: `artifacts/review/2026-04-23-full-stage-130.md`, M2-M5/M7.

После stages 131-133 закрыты privacy boundary, scope preflight и VM API contract drift. Остались эксплуатационные хвосты stage 130:

- `rate_limit_backend.py` уже имеет `shutdown_rate_limit_backend()` (stage 129.6), но `server._graceful_shutdown()` его не вызывает.
- `auth_audit.add_token_usage_log()` пишет structured audit log до durable commit и не добавляет `request_id`/`correlation_id` в audit details/log extra.
- `web._observed_custom_route()` метрит custom routes, но generic exceptions не логирует структурированно; `FormPayloadTooLarge` возвращает raw `PlainTextResponse` без correlation headers.
- `/metrics` при неверном bearer token возвращает 403 без security log и без `auth_failures_total`.
- startup abort использует root `logging.critical(...)`, а не `RUNTIME_LOGGER.critical(event_name="startup_aborted")`.
- `host_resolver.resolve_vetmanager_host()` имеет TTL cache, но concurrent cold-cache calls на один domain не coalesce'ятся.
- Prometheus exporter уже рендерит `vetmanager_token_preset_issued_total` и `vetmanager_sanitizer_failures_total`, но regression coverage не пинует эти families.

## Цель

Закрыть reliability/observability хвосты stage 130 без изменения продуктовой семантики: deterministic shutdown, durable audit signal, request/correlation coverage, `/metrics` auth visibility и cold-cache host-resolution coalescing.

## Scope

1. Подключить `shutdown_rate_limit_backend()` в `server._graceful_shutdown()` через тот же guarded warning pattern, что `reset_shared_http_client`, `reset_breakers`, `reset_billing_resolver`.
2. Перенести structured audit log для token usage events на post-commit path. `add_token_usage_log()` только добавляет DB row и enrich'ит details; единый helper `commit_token_usage_log(session, audit_event)` выполняет commit всей текущей transaction/session (audit row + staged token/stat mutations) и только после успешного commit пишет `AUDIT_LOGGER.info(event_name="token_audit_log_committed")`. Все non-audit mutations должны быть staged до вызова helper.
3. Добавить `request_id`/`correlation_id` в `TokenUsageLog.details_json` и `AUDIT_LOGGER` extra для create/revoke/auth success/failure/rate-limit events, когда HTTP context доступен. Источник: существующий `request_context.get_current_request_context()`, тот же механизм, который наполняет `X-Request-ID`/`X-Correlation-ID`; сигнатура `add_token_usage_log()` не должна требовать ручной передачи id в каждом caller. Enrichment использует allowlist: только `request_id` и `correlation_id`; любые будущие keys request context не копируются.
4. В `_observed_custom_route()` (`web.py`) использовать существующие helpers:
   - вернуть 413 через уже переданный в route registry `plain_text_response(...)`, чтобы сохранить `X-Request-ID`/`X-Correlation-ID`;
   - логировать generic exceptions через `RUNTIME_LOGGER.exception(...)`/`warning(..., exc_info=True)` с `event_name="custom_route_error"`, route, method, status_code, request/correlation context;
   - сохранить existing `record_http_request(...)` behavior.
5. В `/metrics` unauthorized branch (`web_routes_system.py`) логировать `SECURITY_LOGGER.warning(...)` с `request_id`/`correlation_id` из `request_context.get_request_context(request)` и вызывать существующий `service_metrics.record_auth_failure(source="metrics", reason="invalid_token")`, только когда `METRICS_AUTH_TOKEN` задан и request bearer отсутствует/не совпадает.
6. Startup abort перевести на `RUNTIME_LOGGER.critical(..., extra={"event_name": "startup_aborted"})`.
7. Добавить per-loop/per-domain in-flight coalescing в `resolve_vetmanager_host()`: параллельные misses одного domain ждут один leader request; разные domains не блокируют друг друга; failures не кешируются и не оставляют stale in-flight state. Для одновременных callers одного domain leader's `max_retries` wins; follower cancellation не отменяет leader; leader exception re-raise'ится followers и очищает in-flight map; leader `CancelledError` также propagates followers, очищает in-flight map, и followers не становятся новым leader в этом же fan-out. Existing policy "failures are not cached" сохраняется: stage 134 добавляет только transient in-flight map, не negative TTL cache.
8. Расширить Prometheus tests на `token_preset_issued_total` и `sanitizer_failures_total`.
9. Обновить `AssumptionLog.md`, `artifacts/observability-runbook-vetmanager-mcp-ru.md`, Roadmap и work log.

## Non-Scope

- Не менять schema `TokenUsageLog`: request/correlation ids идут в `details_json`, а не в новые DB columns.
- Не вводить distributed lock/coalescing между процессами; stage 134 закрывает single-process thundering herd.
- Не менять authorization semantics `/metrics`: env `METRICS_AUTH_TOKEN` остаётся optional; если env unset, endpoint открыт как раньше.
- Не рефакторить весь auth/audit слой и не переносить audit metadata из `web_security` в отдельный модуль.

## Acceptance

- `server._graceful_shutdown()` закрывает rate-limit backend; regression test проверяет вызов и guarded warning branch.
- `AUDIT_LOGGER` не пишет committed event до durable commit; regression: если `session.commit()` падает, `token_audit_log_committed` отсутствует.
- Все callers token usage audit используют единый post-commit helper: token create, token revoke, auth success, auth failure branches через `_reject`, auth rate-limit branch.
- Token audit details/log extra содержат `request_id`/`correlation_id` в HTTP context и не содержат raw bearer token/API secrets.
- Token audit enrichment копирует только allowlisted context keys (`request_id`, `correlation_id`); regression test доказывает, что дополнительные keys не попадают в `details_json`.
- 413 oversized form response содержит `X-Request-ID` и `X-Correlation-ID`.
- Generic custom-route exception даёт structured runtime log и HTTP metrics status 500.
- Unauthorized `/metrics` при заданном `METRICS_AUTH_TOKEN` и missing/invalid bearer даёт `auth_failures_total{source="metrics",reason="invalid_token"}` и security log с `request_id`/`correlation_id`; при unset env endpoint остаётся open без auth-failure metric.
- Startup secret validation failure пишет `startup_aborted` через `RUNTIME_LOGGER.critical`.
- N параллельных `resolve_vetmanager_host("clinic-a")` при cold cache делают один billing request; разные domains могут идти параллельно; leader exception/cancellation распространяется followers и не оставляет in-flight entry; follower cancellation не отменяет leader; per-loop reset очищает in-flight state.
- Prometheus exporter tests пинуют `vetmanager_token_preset_issued_total` и `vetmanager_sanitizer_failures_total`.

## Decomposition

- 134.1 Tests for shutdown, audit commit boundary, web error/correlation, metrics auth, host coalescing and exporter families.
- 134.2 Implement rate-limit backend shutdown integration.
- 134.3 Implement token audit post-commit logging + request/correlation enrichment.
- 134.4 Implement web route error/correlation and metrics unauthorized observability.
- 134.5 Implement startup abort structured critical log.
- 134.6 Implement host resolver in-flight coalescing.
- 134.7 Update Prometheus exporter tests.
- 134.8 Update runbook/AssumptionLog/Roadmap/work log; run targeted and full suites; audit, commit, external review, push.

Roadmap mapping: PRD groups Roadmap 134.4/134.5/134.6 into implementation slices by touched modules, but final Roadmap statuses remain 134.1-134.10.
