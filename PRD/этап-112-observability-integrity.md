# Этап 112. Observability integrity

## Цель

Закрыть observability-findings super-review 2026-04-19, которые не попали в stage 111 priority. Упор на отсутствующие state-transition логи, privacy в url_path, correlation_id hygiene, retry log noise.

## Scope

### 112.1 Breaker state transition logging

**Проблема:** `vm_transport/breaker.py:146-164 breaker_record_failure` транзиционирует CLOSED → OPEN без структурного лога. Есть парный `circuit_breaker_closed` на recovery (stage 107.9), нет `circuit_breaker_opened` на open — операторы не могут восстановить timestamp trip'а без reverse-engineering counter'ов.

**Решение:** добавить `RUNTIME_LOGGER.warning("Circuit breaker opened", extra={"event_name": "circuit_breaker_opened", "domain": domain, "consecutive_failures": N, "threshold": T})` в двух точках: (a) CLOSED → OPEN по threshold (line 163), (b) HALF_OPEN → OPEN после failed probe (line 152).

**Тест:** unit на `breaker_record_failure` — вызов N раз, проверить что emission происходит ровно один раз на transition, с корректными extra.

### 112.2 Integration save failure logs + metric

**Проблема:** `web_routes_account.py::account_integration_submit` и `::account_integration_reauth_submit` на `except (ValueError, AuthError, HostResolutionError, VetmanagerError)` рендерят HTML с `integration_error=str(exc)` без structured log + без `record_auth_failure`. Support не может grep'нуть event по account_id.

**Решение:** в обоих except-branches добавить:
```python
RUNTIME_LOGGER.warning(
    "Integration save failed",
    extra={
        "event_name": "integration_save_failed",
        "account_id": account_id,
        "error_class": exc.__class__.__name__,
    },
)
record_auth_failure(source="web_integration", reason=exc.__class__.__name__.lower())
```

**Не включать `str(exc)` в extra** — может содержать masked API key fragment (`AuthError` message). class name достаточен.

### 112.3 URL path ID scrubbing

**Проблема:** `vetmanager_client.py:371-382, 395-406, 434-446` retry/timeout/network_error logs содержат `"url_path": path` с customer ID (`/rest/api/client/12345`). Privacy-leak в log aggregation (SRE + support access).

**Решение:** заменить `"url_path": path` на `"entity": _entity_from_path_fn(path)` в 3 лог-сайтах. `_entity_from_path_fn` уже imported в модуле (line 50). Результат: `"entity": "client"` вместо `"url_path": "/rest/api/client/12345"`.

Опциональный gate через `LOG_INCLUDE_URL_IDS=1` env — **не делаю**: scope бы расширил без реального use-case; full path можно извлечь из outbound_correlation_id + upstream log. Можно добавить позже, если операторы запросят.

**Тест:** extending `tests/test_stage88_observability_core.py` — mock timeout, assert `entity == "client"` (не `url_path`).

### 112.4 `correlation_id` explicit в business-event logs

**Проблема:** `web_routes_auth.py:238-242` "Web login succeeded" log + :136 "Account registered" полагаются на `RequestContextLogFilter` для inject'а correlation_id. Если filter silently omits field (non-HTTP context, edge cases), event не join'ится с inbound request.

**Решение:** explicitly pull `correlation_id` через `get_current_request_context()` + pass в `extra`. Pattern уже используется в `vetmanager_client.py:269-270` и `resources/_aggregation.py:124`.

**Тест:** добавить check в existing login/register тесты — log emitted с correlation_id.

### 112.5 Retry log hygiene

**Проблема:** `vetmanager_client.py:316-318` last-attempt retry logs at INFO level. Даже если subsequent retry succeeds, INFO-level event создаёт false alert noise если Grafana alert'и key'ятся на "retry INFO > N".

**Решение:** перевести last-attempt retry log в DEBUG; эскалация в WARNING происходит только на final `VetmanagerTimeoutError`/`VetmanagerError` raise. Альтернатива: добавить `"outcome": "retrying"` в extra чтобы alert queries могли filter.

Выбираю **перевод в DEBUG** — минимальная поверхность, consistent с остальными intermediate retry logs (уже DEBUG).

### 112.6 Per-attempt `elapsed_ms` в retry logs

**Проблема:** `vetmanager_client.py:365-385` `vm_upstream_timeout_retry` log использует `elapsed` посчитанный от `started` — который не reset между retry iterations. На retry N `elapsed_ms` — cumulative, не per-attempt. Неверный для timeout-config диагностики.

**Решение:** `started = time.monotonic()` reset внутри while loop (line 296 уже сбрасывает перед `client.request`, но `elapsed` для retry computation (line 366, 420) использует stale value если first try succeeded и TimeoutException не выбросилось... на самом деле current code reset'ит `started` на line 296 прямо перед каждым `client.request`; `elapsed` line 366 = now - started сразу после. **Проверяю**: current поведение correct — `started` перезаписывается на каждой iteration (line 296). F6 finding неточный.

**Verdict:** не делаю — false-positive, `started` уже per-attempt. Отмечаю в AssumptionLog и dismissed section.

## Non-scope

- Event-name/label enum (Codex blindspot observation — "future drift vector for auth_failures_total"): deferred в stage 114 или отдельный — требует refactor 10+ call-sites.
- Grafana dashboards / alert rules: не в scope, документация ops team.

## Acceptance criteria

1. `breaker_record_failure` эмитит `circuit_breaker_opened` ровно один раз на CLOSED→OPEN transition (threshold crossed) и ровно один раз на HALF_OPEN→OPEN после probe failure.
2. `account_integration_submit` и `_reauth_submit` на exception эмитят `integration_save_failed` log с `account_id` + `error_class`; `auth_failures_total{source="web_integration",reason="..."}` инкрементируется.
3. Все 3 retry/timeout/network_error logs в `vetmanager_client._request` используют `"entity": ...` вместо `"url_path": ...`.
4. `web_login_succeeded` и `account_registered` logs содержат explicit `correlation_id` в extra.
5. Intermediate retry logs в DEBUG (не INFO).
6. Все 687 tests остаются зелёными; добавлены ~6 новых регрессионных тестов.
7. Codex review: 0 critical adequate findings после ≤2 итераций.

## Декомпозиция

| # | Подзадача | LOC | Файлы |
|---|---|---|---|
| 112.1 | breaker_opened log | ~20 | `vm_transport/breaker.py`, `tests/test_stage112_obs_integrity.py` (new) |
| 112.2 | integration_save_failed | ~30 | `web_routes_account.py` |
| 112.3 | url_path → entity | ~15 | `vetmanager_client.py` (3 sites), test |
| 112.4 | correlation_id explicit | ~15 | `web_routes_auth.py` (2 sites) |
| 112.5 | retry log level | ~5 | `vetmanager_client.py:316-318` |
| 112.6 | per-attempt elapsed | 0 | N/A (false positive, skip) |

Total: ~85 LOC code + ~60 tests.

## Simplicity evaluation

Все 9 triggers проверены:
1. Abstraction без 2+ callers — нет новых abstractions.
2. Premature flexibility — `LOG_INCLUDE_URL_IDS` env gate явно отклонён как premature.
3. Indirection — нет.
4. Dual-API surface — нет.
5. Paired sync — нет.
6. State machine — нет.
7. Lazy imports — все на module level.
8. Heavy framework — stdlib logger.
9. Helper from 1 place — нет новых helpers.

**Rationale:** все 5 actual subtasks — точечные вставки 1-5 строк каждая. Нет нового design, только fill-in пропущенных log/metric сайтов.

## План работы

1. 112.1 breaker_opened + test.
2. 112.2 integration save failure log + metric.
3. 112.3 url_path scrubbing + test.
4. 112.4 correlation_id explicit.
5. 112.5 retry log DEBUG.
6. Full suite.
7. Codex review + fixes.
8. Self-attestation + commit.
