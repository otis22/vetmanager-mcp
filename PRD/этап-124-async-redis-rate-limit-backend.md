# Этап 124. Async Redis rate-limit backend

## Контекст

Super-review 2026-04-20 зафиксировал blocker/high проблему в web hot-path: `rate_limit_backend.py` использует sync `redis.Redis` внутри async Starlette handlers. Сейчас каждый `count_in_window` / `record_hit` блокирует event loop на RTT до Redis, а `_ResilientRedisBackend` вызывает sync fallback прямо из async request path.

Это противоречит текущему runtime-контракту web слоя: login/register/lockout и прочие safety controls должны быть async-safe и не сериализовать параллельные запросы на Redis latency.

## Цель

Перевести rate-limit backend на async Redis (`redis.asyncio`) и довести async propagation до web слоя так, чтобы:
- web handlers не блокировали event loop sync Redis-вызовами;
- fallback semantics `_ResilientRedisBackend` сохранились;
- strict mode (`RATE_LIMIT_REQUIRE_REDIS=1`) по-прежнему fail-closed;
- тесты доказывали interleaving, а не скрытую сериализацию.

## Scope

**В scope:**
- `rate_limit_backend.py`
- `web_security.py`
- `web_routes_auth.py`
- `tests/test_rate_limit_backend.py`
- при необходимости точечные web tests, затронутые async propagation

**Вне scope:**
- bearer token limiter (`auth/rate_limit.py`)
- общий request cache / Redis cache
- новые product changes вне rate-limit backend

## Подзадачи

### 124.1 Async backend surface (≤2 ч)

- `RateLimitBackend` protocol → async methods
- `RedisRateLimitBackend` перевести на `redis.asyncio.Redis`
- factory `get_rate_limit_backend()` сделать async-safe инициализацией с `await client.ping()`
- убрать sync `import redis` / `redis.Redis.from_url(...)`

### 124.2 Fallback contract preservation (≤1.5 ч)

- `_ResilientRedisBackend` перевести на async `_safe(...)`
- сохранить strict/non-strict semantics без silent regressions
- fallback backend оставить `InMemoryRateLimitBackend`, но вызывать через async boundary

### 124.3 Web propagation (≤1.5 ч)

- `check_rate_limit`, `record_rate_limit_hit`, `clear_rate_limit_key`, `reset_web_security_state` → async
- адаптировать `web_routes_auth.py` call sites на `await`
- сохранить поведение login/register lockout без product drift

### 124.4 Tests + audit (≤2 ч)

- переписать backend tests на `pytest.mark.asyncio`
- добавить concurrency test: несколько параллельных `await check_rate_limit(...)` / backend calls должны выполняться interleaved
- добавить integration test: factory реально использует `redis.asyncio`, strict mode сохраняется
- полный прогон `docker compose --profile test run --rm test`

## Верификация

- `tests/test_rate_limit_backend.py` покрывает async in-memory, async redis, resilient fallback, strict mode и interleaving
- `web_security.py` больше не вызывает backend sync-методами
- `rg -n "import redis$|redis\\.Redis" rate_limit_backend.py` ничего не находит
- full suite зелёный

## Риски

- Async factory может создать race на первом обращении к backend; если всплывёт, нужен per-loop/global init lock.
- `fakeredis` может иметь отличающийся async API; тесты должны опираться только на реально поддерживаемые методы.
- Если async propagation будет неполной, web tests поймают `RuntimeWarning: coroutine was never awaited` или false-green из-за старых sync вызовов.
