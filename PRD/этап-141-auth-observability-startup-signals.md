# Этап 141. Auth observability and startup signals

## Контекст

Источник: `artifacts/review/2026-04-24-full-stage-136.md`, findings F9/F19/F22.

Цель этапа: закрыть observability gaps в bearer auth failure paths, startup abort logging и operator runbook без изменения runtime auth контракта и без добавления новых внешних зависимостей.

## Проверенные факты

- `auth/request.py::get_bearer_token()` сейчас пишет только `vetmanager_auth_failures_total{source="bearer_header",reason=...}` для missing/invalid Authorization header и не пишет structured security log.
- `auth/bearer.py::resolve_bearer_auth_context()` уже использует `_reject()` для revoked/expired/no_connection/no_scopes/ip_denied/rate_limited с durable `TokenUsageLog`, но invalid token и disabled token/account paths пишут только metric и сразу raise.
- Unknown invalid bearer token не имеет `bearer_token_id`, поэтому durable token usage audit row невозможен; для этого path нужен structured `security` log без raw token.
- Disabled token/account имеет `bearer_token_id`, поэтому должен идти через общий rejection helper и писать durable token audit row.
- `server.py` currently calls `configure_logging()`/`configure_error_tracking()` at module initialization and logs `startup_aborted` only around `validate_required_secrets()`; error tracking setup, storage init, schema bootstrap, transport config and `mcp.run()` failures are not all step-labelled.
- `artifacts/observability-runbook-vetmanager-mcp-ru.md` quick smoke-check omits `METRICS_AUTH_TOKEN` curl example and still says upstream failures include `http_4xx`, while current metrics count timeout/network/breaker/5xx as failures and track all request statuses separately via `vetmanager_upstream_requests_total`.

## Scope

### In scope

1. Add structured security signal for missing/invalid Authorization header without storing raw header/token.
2. Add structured security signal for invalid bearer token lookup without storing raw token.
3. Route disabled token/account rejection through the shared bearer rejection helper with a new token audit event, while preserving caller-visible rejection shape and rejecting even if the new audit write fails.
4. Wrap startup phases with a small step-labelled helper so boot failures emit `startup_aborted` with `step`.
5. Update observability runbook for token-aware `/metrics` smoke check and correct 4xx/5xx upstream guidance.
6. Add focused regression tests for the above.

### Out of scope

- Moving bearer rate limiting to Redis/shared backend (F10/F20/F21 scope, not Stage 141).
- Changing auth error messages or public auth contract.
- Adding durable audit rows for unknown invalid tokens, because no token row exists.
- Full observability runbook rewrite beyond F22.
- Structured `startup_aborted` for failures inside `configure_logging()` itself; logger configuration must run before structured logging exists, so this earliest failure can only use normal Python exception/stderr behavior.

## Security Log Schema

Required fields for new bearer auth security logs:

- `event_name="bearer_auth_failed"`
- `source`: `bearer_header` or `bearer_runtime`
- `reason`: current metric reason
- `request_id` and `correlation_id` when present in request context
- `client_ip` when available through existing trusted-proxy-aware helper

Forbidden fields:

- raw `Authorization` header value
- raw bearer token or token hash
- decrypted Vetmanager credentials

## Acceptance Criteria

- Missing Authorization header records existing metric and emits a structured security log with `event_name="bearer_auth_failed"`, `source="bearer_header"`, `reason="missing_authorization"`.
- Invalid Authorization header records existing metric and emits the same structured security log shape with `reason="invalid_authorization"`.
- Unknown bearer token records existing metric and emits a structured security log with `source="bearer_runtime"`, `reason="invalid_token"`, no raw token, no bearer token id.
- Disabled token/account records existing metric and commits a `TokenUsageLog` event `token_auth_failed_disabled` with safe details.
- Disabled token/account rejection keeps the same caller-visible contract as before: `AuthError`, status code `401`, message `Invalid authorization.`; only the metric and new audit/log signal are observable changes.
- If the new disabled-path `TokenUsageLog` write fails, the request still rejects with the same `AuthError`/401/message shape and emits a structured warning about audit persistence failure.
- Existing revoked/expired/no_connection/no_scopes/ip_denied/rate_limited event semantics remain unchanged.
- Startup failures in `configure_error_tracking`, `validate_required_secrets`, `initialize_storage`, `bootstrap_storage_schema`, transport config parsing and `mcp.run` emit `startup_aborted` with `step`.
- Clean `mcp.run()` return, `KeyboardInterrupt`, and `SystemExit` are not logged as `startup_aborted`.
- Runbook quick check documents both unauthenticated `/metrics` and `METRICS_AUTH_TOKEN` curl forms.
- Runbook upstream guidance says `vetmanager_upstream_failures_total` covers timeout/network/circuit_open/http_5xx, while `vetmanager_upstream_requests_total` carries all upstream statuses including 4xx.
- Tests assert serialized security log records do not contain raw Authorization header values or raw bearer token substrings for header and unknown-token failure paths.
- Targeted tests and full Docker test profile pass.

## Decomposition

1. Tests for auth observability gaps: header failures, invalid token security log, disabled audit event. ≤ 2h / ≤ 150 LOC.
2. Implement auth observability helpers and disabled rejection event. ≤ 2h / ≤ 150 LOC.
3. Tests for startup step-labelled abort logging, including a non-secret startup phase. ≤ 2h / ≤ 150 LOC.
4. Implement startup phase helper in `server.py`. ≤ 2h / ≤ 150 LOC.
5. Update observability runbook and artifact notes. ≤ 2h / docs only.
6. Full checks, audit, external diff review, commit/push, self-attestation. Workflow step.

## Simplicity Notes

- Prefer one local helper in `auth/request.py` for header security logs and one local helper in `auth/bearer.py` for unknown-token security logs. Do not introduce a new observability framework.
- Extend the existing `_reject()` path for disabled token/account instead of creating a parallel audit path.
- Startup wrapper should be a small function that logs and re-raises; no lifecycle framework or decorator system. Keep `configure_logging()` before structured startup logging so logger setup remains deterministic.
