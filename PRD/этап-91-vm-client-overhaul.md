# Этап 91. VM client overhaul — singleton httpx + retry + timeouts + breaker

## Контекст

Baseline F8 (high, performance, confidence 0.95): три связанных дефекта в `vetmanager_client.py::_request`:
- `async with httpx.AsyncClient()` создаётся на каждый вызов — fresh TLS handshake, нет keep-alive (100-400ms overhead/tool).
- `MAX_RETRIES=1` только на timeout/network; нет retry на 429/5xx, нет honor Retry-After.
- Нет circuit breaker — VM outage зависает workers на 30s+.

Single 30s timeout без connect/read split — агрессивно для быстро-failing путей.

## Цель

Привести VM client к production-grade HTTP: pooling, устойчивые retry, timeouts split, circuit breaker. Без breaking changes в публичном API tools.

## Подзадачи

### 91.1 Module-level singleton `httpx.AsyncClient` с Limits

`vetmanager_client.py`:
- `_SHARED_HTTP_CLIENT: httpx.AsyncClient | None` — lazy init через `_get_shared_http_client()`.
- Конфиг: `httpx.Limits(max_keepalive_connections=50, max_connections=100, keepalive_expiry=30.0)`.
- Split timeouts: `httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=2.0)`.
- `_request` использует `await _get_shared_http_client().request(...)` вместо контекст-менеджера.
- `async def close_shared_http_client()` — для тестов и shutdown hooks.
- Startup/shutdown hooks в `server.py` не добавляем в этом этапе — FastMCP cleanup не trivial, lazy init с module-level reference достаточно.

LOC: ≤60.

### 91.2 Retry policy с exponential backoff + Retry-After

- Retry на `response.status_code in {429, 502, 503, 504}` — для идемпотентных методов (GET). POST/PUT/DELETE retry только на transient transport errors (timeout/network), не на 5xx.
- `MAX_RETRIES = 3` для GET, `MAX_RETRIES_WRITE = 0` для POST/PUT/DELETE.
- Backoff: `min(2 ** attempt * 0.2 + jitter, max_backoff)`, max_backoff = 5s.
- `Retry-After` header (seconds или HTTP-date) honored — если больше computed backoff, ждём Retry-After; если меньше — ждём computed backoff.
- `record_upstream_failure` записывается только на финальный fail, не на каждую retry-попытку.

LOC: ≤80.

### 91.3 Circuit breaker per-domain

Простой state machine:
- `CLOSED` (default): все запросы идут.
- `OPEN`: после N=5 consecutive failures в окне 60s → fail-fast с `VetmanagerUpstreamUnavailable` exception на T=30s.
- `HALF_OPEN`: через T секунд → ОДИН запрос пробный. Успех → `CLOSED`; fail → снова `OPEN` с новым 30s cooldown.
- Keyed on `domain`.
- Thread-safe via `asyncio.Lock` per-domain.
- Метрика: `record_upstream_failure(target=..., reason="circuit_open")` на fast-fail.

LOC: ≤100.

### 91.4 Исключение `VetmanagerUpstreamUnavailable`

В `exceptions.py`: новый класс inherit from `VetmanagerError`. Circuit breaker fast-fail поднимает его. Tool-слой уже ловит `VetmanagerError`, поэтому backwards-compatible.

LOC: ≤10.

### 91.5 Тесты

- `test_shared_http_client_is_reused_across_requests` (mock, assert transport creation count)
- `test_retry_on_503_with_exponential_backoff` (mock 503→503→200, assert success; assert timing monotonic+increasing)
- `test_retry_honors_retry_after_seconds` (mock 429 + `Retry-After: 2`, assert sleep 2s)
- `test_post_does_not_retry_on_5xx` (mock 500 on POST, assert call_count=1)
- `test_timeout_split_connect_and_read_separately` (assert via client config introspection)
- `test_circuit_breaker_opens_after_failures` (5 failures → next call raises VetmanagerUpstreamUnavailable fast)
- `test_circuit_breaker_half_open_after_cooldown` (time-travel or manually manipulate breaker state for unit test)
- `test_circuit_breaker_resets_on_success` (half-open success → closed, counter reset)

LOC: ≤200.

### 91.6 Codex review + commit + push

## Вне scope

- `_pace_requests` refactor (убрать serialize на asyncio.gather) — отдельный этап 91b.
- Host resolver process-level TTL cache — отдельный этап 91b.
- Load test на devtr6 — вручную после.

## Acceptance

- Singleton httpx используется во всех `_request`.
- 503 на GET retry'ится с backoff до 3 раз.
- 500 на POST НЕ retry'ится.
- Retry-After header honored.
- Circuit breaker после 5 подряд failures → fast-fail до cooldown.
- Full suite зелёный.
- Codex 0 adequate critical.
