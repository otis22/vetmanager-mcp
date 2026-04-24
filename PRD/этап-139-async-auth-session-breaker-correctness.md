# PRD Этап 139: Async auth/session and breaker correctness

## Цель

Закрыть high/medium findings F5-F6/F15/F17-F18 из full super-review stage 136: корректность concurrent login/password reauth, retry-time breaker accounting, atomic token usage stats, cancellation cleanup в inactive helpers и over-fetch при малом `limit`.

## Источники

- `artifacts/review/2026-04-24-full-stage-136.md` — F5/F6/F15/F17/F18.
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` — актуальная async/runtime архитектура.
- `vetmanager_connection_service.py`, `vetmanager_client.py`, `auth/bearer.py`, `tools/_inactive_helpers.py`.
- Existing tests: `tests/test_vetmanager_connection_service.py`, `tests/test_stage105_breaker_amplification.py`, `tests/test_inactive_helpers.py`, `tests/test_bearer_auth.py`.

## Контекст и проверенные факты

- `save_user_login_password_connection()` нормализует domain, но `_ACCOUNT_LOGIN_PREPARE_TASKS` сейчас keyed only by `account_id`.
- `_run_login_prepare_once()` awaits shared task directly; caller cancellation can cancel the shared task for other waiters.
- `vetmanager_client.VetmanagerClient._request()` calls `_check_breaker_allows(domain_key)` before each retry. Retry-time denial can leave `_breaker_resolved=False`, so `finally` records a fresh breaker failure.
- `auth/bearer.py` updates `TokenUsageStat` via lookup-then-insert and read/modify/write increment after token auth success.
- `storage_models.TokenUsageStat.bearer_token_id` has `unique=True`; baseline migration also creates `uq_token_usage_stats_bearer_token_id`.
- Runtime bearer auth canonical implementation is `auth/bearer.py`; top-level `bearer_auth.py` is a BC shim re-exporting the same `resolve_bearer_auth_context` function.
- `tools/_inactive_helpers._gather_bounded()` uses `asyncio.gather()` without explicit sibling cancel/await cleanup.
- `find_pets_for_clients_last_visit()` groups clients by day and fetches pets/invoices/medical cards for whole day groups before final caller truncation.

## Оценка простоты

- Login/password coalescing: keep existing task cache, change key to immutable account/domain/fingerprint tuple and `asyncio.shield(task)`; no new queue/service layer.
- Breaker accounting: set `_breaker_resolved=True` only around retry-time `VetmanagerUpstreamUnavailable`; do not restructure the request loop.
- Token usage stats: use SQLAlchemy Core insert-do-nothing plus atomic `UPDATE request_count = request_count + 1` for SQLite/Postgres; no process-local lock as final fix.
- `_gather_bounded`: use explicit task creation + cancel-and-await on first exception; no broad TaskGroup migration if Python 3.11 compatibility surface needs no new abstraction.
- Over-fetch: cap subsequent day scheduling and medcard fallback after quota is filled; within-day pet chunk fan-out remains accepted debt in this stage.

## Scope

1. Login/password prepare coalescing:
   - Key in-flight prepare task by account id + normalized domain + credential fingerprint.
   - Fingerprint is a one-way SHA-256 digest over normalized domain/login/password with a separator; raw login/password must not be stored in task-cache keys or logs.
   - Shield shared task awaits from caller cancellation.
   - Cleanup task cache when owner task completes.
2. Breaker retry-time denial accounting:
   - Ensure retry-time breaker denial does not call `_breaker_record_failure()` in `finally`.
   - Preserve cancellation cleanup for unexpected task cancellation.
3. Token usage stats:
   - Insert stats row if missing via dialect-aware conflict-ignore or equivalent SQLAlchemy Core path.
   - Increment request_count atomically with one `UPDATE` expression.
   - Auth success must not become 500 solely because stats row contention occurs; log stats-update failures without exposing token secrets.
4. Inactive helper cancellation cleanup:
   - `_gather_bounded()` cancels and awaits sibling tasks on first failure.
5. Inactive helper over-fetch:
   - Do not schedule/fetch subsequent day work once `limit` remaining quota is filled.
   - Do not schedule medcard fallback for a day whose invoice pass already filled quota.
   - Within-day pet chunk fan-out is out-of-scope for stage 139 and recorded as accepted debt.
6. Docs/artifacts:
   - Update AssumptionLog and Roadmap.

## Out of Scope

- Rewriting VetmanagerClient retry/breaker architecture.
- Changing public MCP tool schemas.
- Changing inactive-clients business semantics or date window contract.
- Full redesign of within-day inactive pet chunk fan-out.
- Real API e2e.

## Декомпозиция

### 139.1 PRD and review gates

- Создать PRD, изучить artifacts, пройти PRD-review gates.
- Closes: workflow requirement.
- Оценка: docs-only.

### 139.2 Login/password prepare coalescing and shield

- Implement keyed prepare task cache with credential fingerprint.
- Await shared prepare task through `asyncio.shield()`.
- Tests: concurrent different credentials do not mix domain/token; cancelled waiter does not cancel shared exchange for another waiter; fingerprint does not contain raw password.
- Closes: F5.
- Оценка: ≤ 150 строк.

### 139.3 Breaker retry-time denial accounting

- Treat retry-time `VetmanagerUpstreamUnavailable` as resolved outcome before re-raise.
- Tests: retry-time denial does not increment breaker failure count or self-open/re-open.
- Closes: F6.
- Оценка: ≤ 80 строк.

### 139.4 TokenUsageStat race hardening

- Add atomic insert/update for usage stats.
- Tests: concurrent first successful auth requests leave one stats row and no lost increments.
- Closes: F15.
- Оценка: ≤ 150 строк.

### 139.5 `_gather_bounded` sibling cleanup

- Explicitly cancel/await remaining tasks when one coroutine fails.
- Tests: failing coroutine cancels pending sibling work deterministically using an `asyncio.Event`/barrier so the sibling cannot finish naturally before cancellation.
- Closes: F17.
- Оценка: ≤ 100 строк.

### 139.6 Inactive helpers over-fetch cap

- Stop scheduling/fetching subsequent day work once remaining `limit` is filled; skip medcard fallback when invoice pass fills the quota.
- Tests: `limit=1` with multiple day groups does not schedule later days after quota is met; invoice-filled day does not schedule medcard fallback.
- Closes: F18.
- Оценка: ≤ 120 строк.

### 139.7 Checks, audit, external diff review, commit/push

- Targeted tests, full Docker suite, audit, external code/diff review, commit/push, self-attestation.
- Оценка: workflow.

## Acceptance

- Concurrent login/password submissions with different domain/login/password cannot persist one request's domain with another request's token.
- Login/password prepare cache key does not store raw login/password.
- Cancelling one waiter for a shared login/password prepare task does not cancel the shared exchange for other waiters.
- Retry-time breaker denial does not count as a new upstream failure.
- Unexpected cancellation still clears HALF_OPEN `probe_in_flight`.
- Concurrent first bearer auth successes do not create duplicate `TokenUsageStat` rows or lose increments.
- Token usage stat race handling does not turn otherwise successful bearer auth into a 500 solely due to stats contention.
- `_gather_bounded()` does not leave sibling tasks running after first failure.
- Inactive pet lookup with a small `limit` avoids scheduling subsequent day work after the requested quota is filled.
- Inactive pet lookup skips medcard fallback for a day whose invoice pass already filled the quota.
- Targeted tests and full suite pass.
