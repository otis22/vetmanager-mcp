# Этап 115. Real concurrency tests

## Цель

Добавить behavioral concurrency тесты, которые ловят race-conditions без sequential-mock шоу. Закрывает findings T3 из super-review 2026-04-19.

## Scope

### 115.1 Breaker concurrent amplification test

**Проблема:** `tests/test_stage105_breaker_amplification.py:68-110 test_retry_aborts_when_breaker_trips_mid_loop` использует `monkeypatch(asyncio.sleep)` callback → это sequential simulation, не реальная concurrency. True race не ловится.

**Решение:** новый тест в `tests/test_stage115_concurrency.py`: 8 concurrent `VetmanagerClient.get()` calls через `asyncio.gather` на один endpoint. respx mock всегда возвращает timeout. Assert: ≤ `BREAKER_FAILURE_THRESHOLD + N_concurrent` failures (не `8 × MAX_RETRIES = 24`). Stage 105 amplification bug манифестировался бы как >> этого.

### 115.2 Shared pool concurrent singleton test

**Проблема:** `tests/test_stage106_reliability.py:99-120` читает `_shared_http_clients` dict + `current_loop_key()` — implementation-bound. Behavioral test: 8 concurrent `get_shared_http_client()` → все identical.

### 115.3 Service metrics autouse reset fixture

**Проблема:** `service_metrics._BUSINESS_EVENTS_TOTAL` (stage 110) + other counters — process-global, не reset'ятся между тестами. Stage 110 тесты вручную `reset_service_metrics()`; другие могут забыть.

**Решение:** autouse fixture в `conftest.py` `_reset_service_metrics_state` перед каждым тестом. Обеспечивает per-test isolation.

## Non-scope

- id(loop) → WeakKeyDictionary refactor (stage 113.4): в 113b. Тест пока принимает `id(loop)` design as-is.
- Property-based state machine tests: nice-to-have, defer.

## Acceptance

1. `test_breaker_concurrent_amplification`: 8 concurrent gets → total failures ≤ threshold + small buffer; test passes with current code (stage 105 fix holds).
2. `test_shared_pool_concurrent_singleton`: 8 concurrent `get_shared_http_client()` → all same object identity.
3. Autouse `_reset_service_metrics_state` fixture добавлена; существующие стадии, вызывающие вручную `reset_service_metrics()` на входе теста, работают без изменений.
4. 701 → 703+ tests.

## Декомпозиция

| # | Подзадача | LOC |
|---|---|---|
| 115.1 | Concurrent amplification test | ~50 |
| 115.2 | Concurrent singleton test | ~25 |
| 115.3 | Autouse fixture | ~10 |

Total: ~85 LOC.
