# Этап 113. Resilience completeness — billing-api hardening + breaker env accessors

## Цель

Закрыть F7 (billing-api resilience) из super-review 2026-04-19 Codex-арбитража + 113.1 (module-import env eval fix). Остальные breaker/pool concurrency items (113.2-113.5) deferred в stage 113b с дизайн-требованиями.

## Scope

### 113.F7 billing-api resolver hardening (HIGH from super-review)

**Проблема (текущий `host_resolver.py`):**
- Свежий `httpx.AsyncClient` на каждый вызов (TLS handshake per call)
- Нет circuit breaker — при billing outage каждый tenant call висит 30s × N
- Нет resolver cache — при cold start parallel aggregators double-resolve
- Единственный retry с `0.1*(attempt+1)` linear backoff без jitter, без Retry-After
- Timeout 30s на простой JSON lookup (должен быть <1s nominal)

**Решение:**
1. **Module-level `httpx.AsyncClient`** с tight timeouts (connect=3s, read=10s, write=5s, pool=2s). Shared keep-alive pool = zero TLS handshakes в hot path.
2. **TTL cache `(domain) → resolved_origin`** с TTL=300s. Keyed only by `domain` (API key не участвует в resolution — billing API принимает domain, api_key был параметром но удалён в stage 62). Simple `asyncio.Lock` + dict с expiry time.
3. **Dedicated circuit breaker `_BILLING_BREAKER`** — не per-tenant, один общий для billing-api. Reuse pattern `vm_transport.breaker.DomainBreaker` instance (domain="billing_api"). Когда open — мгновенный raise вместо ожидания timeout.
4. **Exponential backoff с jitter** через `vm_transport.retry.backoff_seconds`. `max_retries=2` (было 1). Honor `Retry-After` header.
5. **Graceful shutdown** — existing `reset_shared_http_client` + новый `reset_billing_resolver` (close AsyncClient + clear cache) вызывается из `server.py` shutdown path.

**Вне scope (deferred):**
- Honor `api_key` в cache key — no-op, billing endpoint API key-less.
- Metrics breaker state transitions — те же что stage 112 (автоматически через `breaker_record_*`).

### 113.1 Breaker/pool env eval accessors (codex-blindspot H10)

**Проблема:** `BREAKER_FAILURE_THRESHOLD`, `BREAKER_WINDOW_SECONDS`, `BREAKER_COOLDOWN_SECONDS` в `vm_transport/breaker.py:31-33` вычисляются на module import. Tests с `monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "2")` не имеют эффекта — module уже импортирован, constants baked in.

**Решение:** заменить module-level constants на accessor functions (`_breaker_failure_threshold()`, etc.), вычисляющие lazily при каждом вызове. Зеркально `auth/rate_limit.py::get_bearer_rate_limit_requests()` pattern. Backward compat: оставить `BREAKER_FAILURE_THRESHOLD` как module attribute для existing test-patches → `@property`-style module-level getattr.

**Альтернатива рассмотрена и отклонена:** settings-class с caching. Требует migrate всех call-site + conftest fixture — out of scope этапа.

## Non-scope (deferred)

Следующие items **явно deferred** в stage 113b/c с design-требованиями (не dismiss, а явная очередь):

- **113.2 probe_in_flight TOCTOU** — stage 106.1 finally уже ловит. Real-world impact: **cancellation window before `try:` blок** (~2 lines). Требует careful ordering: move `_check_breaker_allows` в outer try/finally. Risk регрессии средний. Отдельный stage.
- **113.3 breaker 5xx retry accounting** — fundamental semantics change. Current: 3 retry-503 = 1 breaker failure. Desired: 3 failures. Но retries — это same logical call, double-counting может тоже быть неверным. Требует design: "per-retry vs per-call" decision; document в AssumptionLog. Отдельный stage.
- **113.4 `id(loop)` → `WeakKeyDictionary`** — refactor `vm_transport.pool`. Потребует переписать `current_loop_key` contract + migrate 2-3 тестов, которые читают `_shared_http_clients` by id. Отдельный stage.
- **113.5 `asyncio.Lock` module-scope** — связан с 113.4. Lazy construction pattern. В рамках того же рефакторинга.

## Acceptance

1. `host_resolver.resolve_vetmanager_host` на 10 параллельных calls одного domain → 1 TLS handshake, 1 HTTP request (все последующие hit cache). Существующий host resolver тест обновлён под новое поведение.
2. При billing-api 30-секундном outage: 10 параллельных calls → breaker trips после threshold failures, остальные мгновенно raise `VetmanagerUpstreamUnavailable`.
3. `monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "2")` корректно меняет pороg в `breaker_record_failure` (новый тест).
4. Все 690 tests зелёные; ~4 новых регрессионных теста.
5. Codex review: 0 critical adequate findings после ≤2 итераций.

## Декомпозиция

| # | Подзадача | LOC | Файлы |
|---|---|---|---|
| 113.F7.a | Module-level AsyncClient + TTL cache | ~70 | `host_resolver.py` |
| 113.F7.b | Billing breaker (dedicated, reuse breaker types) | ~30 | `host_resolver.py` |
| 113.F7.c | server.py shutdown hook for billing resolver | ~10 | `server.py`, `host_resolver.py` |
| 113.1 | Env accessors | ~30 | `vm_transport/breaker.py` |
| 113.*.tests | Tests для F7 + 113.1 | ~100 | `tests/test_stage113_resilience.py` (new) |

Total: ~240 LOC.

## Simplicity evaluation

1. Abstraction без 2+ callers — resolver cache и billing breaker имеют 1 call-site, но они инкапсулируют stateful resilience policy (каждая abstraction оправдана functional cohesion, не code reuse).
2. Premature flexibility — `max_retries` оставляю как параметр для testability. `BILLING_CACHE_TTL_SECONDS` env-tunable.
3. Indirection — `resolve_vetmanager_host` → cache hit fast-path; cache miss → breaker check → httpx call. 2 hops, не больше.
4-9. Остальные triggers — не срабатывают.

**Rationale:** F7 unavoidably introduces 2 new stateful abstractions (cache + breaker instance) — без них resilience properties недостижимы. Alternative "inline everything в resolve_vetmanager_host" даёт 80-line procedure без testability в изоляции.

## План

1. Tests-first для F7 (4-5 tests: cache hit, TLS single-handshake, breaker open on degradation, retry with jitter, shutdown close).
2. Tests-first для 113.1 (1-2 tests: monkeypatch env override → threshold changes).
3. Implement 113.1 (less риск, независимо от F7).
4. Implement F7 step by step: AsyncClient lifecycle → TTL cache → breaker → shutdown integration.
5. Full suite.
6. Codex review + fixes.
7. Self-attestation + commit.
