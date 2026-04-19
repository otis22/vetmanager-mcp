# Этап 113b. Breaker/pool concurrency hardening

## Цель

Закрыть deferred concurrency/reliability findings из super-review 2026-04-19, уже зафиксированные в `Roadmap.md` как stage 113b. Фокус: убрать residual race/loop-lifecycle риски без расширения public API.

## Scope

### 113b.1 `probe_in_flight` TOCTOU cleanup

Проверить и закрепить тестами, что cancellation/неожиданный выход между breaker admission и нормальным breaker hook не оставляет домен wedged в `HALF_OPEN`.

Решение:
- сохранить current `finally`-guard в `VetmanagerClient._request`;
- добавить regression test на scenario с forced HALF_OPEN + cancellation;
- audit, что ветка `finally` не double-count'ит failure в normal paths.

### 113b.2 Breaker per-retry 5xx accounting

Текущий код считает breaker failure для terminal 5xx только один раз за logical call. Для sustained upstream degradation это открывает breaker слишком поздно: 5 retry-503 calls дают 5 logical failures, хотя upstream уже ответил 20+ раз кодом 503.

Решение:
- для retryable `GET` status `502/503/504` писать breaker failure на каждой retry iteration;
- при terminal 5xx не делать duplicate accounting сверх уже записанных per-attempt failures;
- `429` не считать breaker failure: это rate limiting, не health signal upstream-а;
- зафиксировать decision в AssumptionLog.

### 113b.3 `id(loop)` → `WeakKeyDictionary`

`vm_transport.pool` и `host_resolver` сейчас ключуют per-loop state через `id(asyncio.get_running_loop())`. Это оставляет residual correctness risk при reuse object id после закрытия loop.

Решение:
- заменить registry на `WeakKeyDictionary[AbstractEventLoop, ...]`;
- сохранить observable BC surface для tests (`_shared_http_clients` и introspection helper) в стабильной форме;
- адаптировать тесты, которые сейчас ожидают int loop keys.

### 113b.4 `asyncio.Lock` lazy/per-loop construction

Module-scope `asyncio.Lock()` создаётся import-time в `vm_transport.pool` / `vm_transport.breaker`. На Python 3.10+ это обычно работает, но это ненужный loop-binding risk и прямо указан в Roadmap.

Решение:
- в `vm_transport.pool` сделать lock lazy-init под first use;
- в `host_resolver` тоже не создавать loop-bound lock на import-time;
- `vm_transport.breaker` module-scope lock оставить только если он не loop-bound в current runtime; если для clean fix нужен lazy-init — сделать в том же проходе.

## Non-scope

- Полный redesign breaker semantics beyond items 113b.1-113b.4.
- Новые product/docs/workflow findings из повторного super-review — они идут отдельными этапами 118/119.
- Codebase-wide simplicity cleanup — stage 114b.

## Acceptance

1. Concurrency stress/cancellation test не оставляет `probe_in_flight=True`.
2. Sustained retryable 503/502/504 открывает breaker по per-attempt accounting, а не по per-call accounting.
3. `429` не триггерит breaker opening.
4. `vm_transport.pool` не использует `id(loop)` для registry; closed loops auto-evict via weak refs.
5. `host_resolver` не использует `id(loop)` для shared clients/locks.
6. Нет import-time `asyncio.Lock()` в изменённых loop-bound registries.
7. Full test suite зелёный.

## Декомпозиция

| # | Подзадача | LOC | Файлы |
|---|---|---:|---|
| 113b.1 | Regression tests for breaker cleanup | ~30 | `tests/test_stage113b_concurrency.py` |
| 113b.2 | Per-retry 5xx accounting + tests | ~40 | `vetmanager_client.py`, `tests/test_stage113b_concurrency.py`, `AssumptionLog.md` |
| 113b.3 | WeakKeyDictionary migration | ~45 | `vm_transport/pool.py`, `host_resolver.py`, related tests |
| 113b.4 | Lazy lock construction | ~20 | `vm_transport/pool.py`, `host_resolver.py`, maybe `vm_transport/breaker.py` |

Total target: ~135 LOC net logic + tests, без broad refactor.

## Rationale для выбранной сложности

- Более простой вариант "оставить `id(loop)` и только документировать risk" уже исчерпан: risk повторно подтверждён full-review и остаётся в Roadmap как `todo`.
- Более сложный вариант "общий reusable loop-state manager package" отклонён: один call-site pair (`vm_transport.pool`, `host_resolver`), premature abstraction.
- Для breaker accounting выбран targeted policy для `502/503/504`, а не "count any retryable status", чтобы не смешивать `429` rate limiting с upstream health.
