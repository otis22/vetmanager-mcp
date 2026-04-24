# PRD Этап 138: Rate limiting and deployment smoke reliability

## Цель

Закрыть high/medium findings F3-F4/F10/F20-F21 из full super-review stage 136: bounded Redis I/O для rate-limit backend, token-aware deployment smoke checks, shared bearer rate limiting, degradation metrics и docs sync.

## Источники

- `artifacts/review/2026-04-24-full-stage-136.md` — F3/F4/F10/F20/F21.
- `rate_limit_backend.py`, `auth/rate_limit.py`, `web_security.py`.
- `scripts/post_deploy_smoke_checks.sh`.
- `service_metrics.py`.
- `README.md`, `artifacts/security-threat-model-vetmanager-mcp-ru.md`.

## Контекст и проверенные факты

- Web auth/register/login rate limiting уже использует `rate_limit_backend.py`, который может работать через Redis при `REDIS_URL`.
- `Redis.from_url(...)` сейчас создаётся без explicit `socket_connect_timeout`/`socket_timeout`; `ping()` и runtime Redis ops await'ятся напрямую.
- Bearer runtime limiter сейчас process-local in-memory (`auth/rate_limit.py`) и не разделяет Redis backend с web limiter.
- Bearer auth resolution уже работает с persisted `ServiceBearerToken.id`; rate-limit call site can use this internal non-secret id after token lookup, without putting raw bearer token into Redis keys.
- `/metrics` runtime требует `Authorization: Bearer $METRICS_AUTH_TOKEN`, если env задан; `scripts/post_deploy_smoke_checks.sh` всегда дергает `/metrics` без header.
- Docs drift: web limiter уже может быть Redis-backed, а bearer limiter до stage 138 process-local.

## Оценка простоты

- Redis timeouts: использовать существующий `_ResilientRedisBackend` boundary и локальные timeout constants/env reads; новый backend layer не добавлять.
- Bearer limiter: прямой вызов `RateLimitBackend.consume_hit(...)` с namespace `bearer`; отдельный namespace abstraction не добавлять.
- Smoke script: расширить существующий `perform_request`/`retry_request`, не вводить новый script.

## Scope

1. Redis backend bounded I/O:
   - настроить `socket_connect_timeout`, `socket_timeout`, `health_check_interval`;
   - обернуть Redis `ping()` и runtime operations в bounded timeout.
2. Degradation signal:
   - добавить metric/counter для Redis rate-limit backend failures/degraded fallback.
3. Bearer limiter:
   - заменить process-local bearer limiter на shared `RateLimitBackend.consume_hit(...)` path с namespace для bearer tokens;
   - namespace/key bearer limiter не должен коллидить с web limiter keys;
   - в Redis key не попадать raw bearer token; использовать internal bearer token id как non-secret identifier.
4. Deployment smoke:
   - `/metrics` probe добавляет bearer header при `METRICS_AUTH_TOKEN`;
   - unauth path остаётся для env unset.
5. Docs:
   - README/security threat model различают web/bearer shared backend после stage 138.

## Out of Scope

- Новые Redis deployment requirements кроме existing `REDIS_URL`/`RATE_LIMIT_REQUIRE_REDIS`.
- Изменение token scope/preset policy.
- Переработка всей metrics taxonomy.
- Horizontal scaling orchestration outside app process.

## Декомпозиция

### 138.1 PRD and review gates

- Создать PRD stage 138, изучить artifacts, пройти PRD-review gates.
- Closes: workflow requirement.
- Оценка: docs-only.

### 138.2 Redis bounded I/O

- Добавить conservative constants/env read в текущей точке Redis client creation без нового abstraction layer.
- Применить к Redis client creation and ping.
- Обернуть Redis backend methods в существующем `_ResilientRedisBackend` boundary.
- Tests: Redis factory receives timeout kwargs; timeout triggers fallback/log.
- Closes: F3.
- Оценка: ≤ 150 строк.

### 138.3 Degradation metric

- Добавить metric snapshot/export для rate-limit backend degraded/failures.
- Metric contract: `vetmanager_rate_limit_backend_degraded_total{reason}` через existing Prometheus exporter.
- Tests: metric increments on Redis operation failure/timeout.
- Closes: F20.
- Оценка: ≤ 100 строк.

### 138.4 Shared bearer limiter

- Перевести bearer limiter на `RateLimitBackend.consume_hit(namespace="bearer", key=token_id, ...)`.
- Удалить/обновить test-only compatibility surface, если старый helper больше не нужен; сохранять public names только если runtime imports require them.
- Tests: bearer limit uses shared backend and still enforces limit/window; reset remains deterministic.
- Closes: F10.
- Оценка: ≤ 150 строк.

### 138.5 Metrics smoke auth

- Добавить auth-aware curl path in `scripts/post_deploy_smoke_checks.sh`.
- Tests: script contains/uses Authorization header when `METRICS_AUTH_TOKEN` is set.
- Tests: script fails non-zero if token is set but `/metrics` still returns 401/403.
- Closes: F4.
- Оценка: ≤ 80 строк.

### 138.6 Docs sync

- README/security threat model: web and bearer rate limiting use shared backend; Redis recommended/required for multi-worker production depending on env.
- AssumptionLog update.
- Closes: F21.
- Оценка: ≤ 80 строк.

## Acceptance

- Redis rate-limit backend cannot block indefinitely on connect/ping/runtime ops.
- Redis backend degradation has metric visibility through the existing `/metrics` exporter.
- Default policy remains availability-preserving fail-open to in-memory fallback on Redis operation timeout/error with degradation metric/log.
- Strict mode (`RATE_LIMIT_REQUIRE_REDIS=1`) remains fail-closed: Redis init failure aborts as today, and runtime Redis operation timeout/error rejects the rate-limit operation instead of silently downgrading to process-local enforcement.
- Bearer token rate limiting is no longer process-local-only when `REDIS_URL` is configured.
- Bearer limiter uses an isolated namespace/key from web limiter keys; Redis keys never include raw bearer token values.
- Post-deploy smoke checks pass against secured `/metrics` when `METRICS_AUTH_TOKEN` is provided.
- Post-deploy smoke checks still pass against open `/metrics` when `METRICS_AUTH_TOKEN` is unset.
- Post-deploy smoke checks fail non-zero when `METRICS_AUTH_TOKEN` is set but `/metrics` returns 401/403.
- README and security threat model describe actual limiter behavior after stage 138: shared backend, Redis condition, degradation fallback, and strict mode.
- Targeted tests and full suite pass.
