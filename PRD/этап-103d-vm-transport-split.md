# Этап 103d — Split `vetmanager_client.py` на `vm_transport/*`

## Цель

`vetmanager_client.py` разросся до 752 LOC и смешивает 5 независимых concern'ов: shared HTTP client pool, per-domain circuit breaker, retry/backoff, cache policy, и оркестрацию VM REST запросов. Splitting в `vm_transport/` package позволяет:

- читать каждый модуль за минуту (vs. 752-LOC монолит);
- менять retry policy или cache TTL без риска задеть breaker state;
- тестировать submodules в изоляции;
- снизить когнитивную нагрузку при PR-review.

## Scope

**Извлекаем:**
1. `vm_transport/retry.py` — `_parse_retry_after`, `_backoff_seconds`, retry-related constants (`MAX_RETRIES_READ/WRITE`, `_RETRY_STATUS_CODES`, `_BACKOFF_*`, `_RETRY_AFTER_MAX_SECONDS`).
2. `vm_transport/cache_policy.py` — `CACHE_TTL_SECONDS`, `CACHE_TTL_SHORT_SECONDS`, `_SHORT_TTL_ENTITIES`, `entity_from_path` (вынос метода в free function).
3. `vm_transport/pool.py` — `_shared_http_clients` dict, `_get_shared_http_client`, `_current_loop_key`, `reset_shared_http_client`, `_SharedClientProxy`, `_shared_http_client` sentinel, `_REQUEST_TIMEOUTS`, `_HTTP_LIMITS`, `get_shared_http_client_state`.
4. `vm_transport/breaker.py` — `_DomainBreaker`, `_breakers`, `_breakers_global_lock`, `_get_breaker`, `_check_breaker_allows`, `_breaker_record_success`, `_breaker_record_failure`, `reset_breakers`, `get_breaker_state`, `force_breaker_open`, `_BREAKER_*` constants, `_env_float/_env_int` helpers.

**Остаётся в `vetmanager_client.py`:**
- `VetmanagerClient` class (thin orchestrator, ~335 LOC → ~290 after extraction).
- Re-exports всех public/test-helper символов (conftest.py, tests и server.py продолжают импортировать из `vetmanager_client`).
- `_masked_secret` helper (только для `_raise_for_status`).

## Non-scope

- Изменения в сигнатурах публичных API (breaker state, retry policy args).
- Добавление новых тестов — существующие 648 должны продолжать работать без модификаций.
- Optimize/refactor логики (сохранить behavior-preserving).

## Критические факты BC

1. `tests/conftest.py:_reset_vm_client_state` делает `_vm_client._shared_http_clients.clear()` и `_vm_client._breakers.clear()`. Это работает потому что dict.clear() мутирует объект по ссылке — если vm_transport.pool и vetmanager_client ссылаются на один и тот же dict, clear через любой alias валиден.
2. Тот же fixture делает `_vm_client._shared_http_client = None` (reassignment sentinel). Это rebind на module level — должен остаться поддерживаемым.
3. `server.py` импортирует `reset_breakers, reset_shared_http_client` из `vetmanager_client` (top-level).
4. Тесты монкипатчат `_vm_client._RETRY_AFTER_MAX_SECONDS`, `_vm_client._BREAKER_FAILURE_THRESHOLD` и т.п. — эти константы должны остаться re-exported из vetmanager_client.
5. `vm_client.asyncio.sleep` патчится в `tests/test_stage102_aggregator_structured_errors.py` — `asyncio` должен остаться импортируемым в vetmanager_client.

## План работы

1. **retry.py** (самое изолированное, pure functions) — extract, re-export, run tests.
2. **cache_policy.py** (trivial constants) — extract, re-export, run tests.
3. **pool.py** (stateful, но изолированно) — extract, re-export с вниманием к sentinel + proxy, run tests.
4. **breaker.py** (последний, больше всего state) — extract, re-export, run tests.
5. **Codex review** на уровне всего `vm_transport/`.
6. **Commit** только после clean review + 648 passed.

Каждый шаг завершается полным прогоном `docker compose --profile test run --rm test` — откат при любой регрессии.

## Acceptance

- `vetmanager_client.py` ≤ 350 LOC (down from 752).
- `vm_transport/__init__.py` + 4 submodule файлов, каждый ≤ 180 LOC.
- Все 648 тестов passed, ноль warnings.
- `conftest.py`, `server.py`, все test imports работают без изменений.
- `scripts/lint_api_contracts.py` clean.
- Codex review: 0 critical, 0 warning после 1-2 итераций.
