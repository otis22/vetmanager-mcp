# PRD — Этап 198: Activation telemetry and new-account funnel

## Статус

Done — implemented, reviewed, deployed to production, and smoke-verified on
2026-07-10.

## Контекст и проблема

Этапы 196, 197 и 199 улучшили activation UX: мобильное подключение Vetmanager,
one-click Bearer token и activation-first кабинет. После этих правок нужно
видеть, где новые пользователи всё ещё отваливаются.

Текущее состояние:

- `/metrics` уже экспортирует aggregate
  `vetmanager_activation_funnel_accounts{stage=...}` из DB scan в
  `activation_telemetry.scan_activation_telemetry`.
- Существующие stages coarse: `registered`, `connected`, `with_active_tokens`,
  `ready_for_mcp`, `with_recent_usage_7d`.
- `scripts/product_metrics_report.py` уже считает richer activation states:
  `needs_connection`, `needs_token`, `needs_client_use`.
- `integration_save_failed` есть только structured log + auth failure metric.
  В нём нет device class и нет persisted product event по account_id.
- `token_copied` есть как in-memory business event counter и safe structured
  log, но после restart counter теряется и событие нельзя связать с account
  funnel.
- Grafana сейчас не показывает воронку новых аккаунтов:
  registered → integration_failed/saved → token_issued → token_copied →
  first_mcp_request.

## Цель

Сделать PII-free activation funnel для новых аккаунтов в Prometheus/Grafana и
персистентно фиксировать ключевые activation product events:

- failed integration attempt;
- saved integration;
- token copied;
- first MCP request already available through token usage state.

## Не цели

- Не сохранять raw domain, email, API key, login, password, Bearer token, user
  agent string или error text в activation telemetry.
- Не строить per-account Grafana labels.
- Не менять UX форм, OAuth flow или MCP tool contract.
- Не заменять existing `business_events_total`; stage 198 дополняет его
  persisted activation telemetry.
- Не добавлять mobile/desktop JavaScript fingerprinting; device class должен
  быть coarse and safe.

## Архитектурное решение

### Проблема

Нужна activation funnel analytics, переживающая process restart и позволяющая
считать новые аккаунты/отвалы по account_id, но Prometheus labels не должны
содержать PII или unbounded cardinality.

### Контекст и ограничения

- Storage уже содержит `accounts`, `vetmanager_connections`,
  `service_bearer_tokens`, `token_usage_stats`.
- `/metrics` уже делает DB scan после metrics auth и обновляет in-memory
  gauges.
- `service_metrics.record_business_event` strict allowlist защищает counter
  cardinality.
- Grafana/Prometheus должны видеть только aggregate labels.
- Existing product metrics CLI уже считает account-state funnel из DB.
- Account UI POST routes уже имеют session + CSRF and can pass account_id.

### Рассмотренные варианты

1. **Only logs + Prometheus counters**
   - Плюсы: минимально.
   - Минусы: process-local counters теряются, logs сложно агрегировать по
     new-account funnel, нет account_id state join.

2. **New persisted `activation_events` table + aggregate gauges**
   - Плюсы: durable, bounded schema, можно считать new-account funnel windows,
     labels остаются aggregate-only.
   - Минусы: новая миграция и cleanup policy.

3. **Reuse token audit logs**
   - Плюсы: меньше таблиц.
   - Минусы: audit log semantics не равны product events; integration failures
     до token issuance туда не ложатся естественно; риск смешать audit и
     product analytics.

Выбран вариант 2.

### Выбранное решение

Добавить таблицу `activation_events` with additive migration:

- `id`;
- `created_at`;
- `account_id` with cascade delete when account is deleted;
- `event_name` allowlist:
  `integration_failed`, `integration_saved`, `token_copied`;
- `auth_mode` nullable allowlist: `domain_api_key`, `user_token`, `unknown`;
- `device_class` allowlist: `mobile`, `desktop`, `unknown`;
- `reason_class` nullable allowlist:
  `auth_error`, `host_resolution_error`, `vetmanager_error`,
  `validation_error`, `unknown`;
- `copy_kind` nullable allowlist: `token`, `config`, `mcp_url`, `unknown`.
- indexes:
  `(created_at)`, `(account_id, created_at)`, `(event_name, created_at)`,
  `(event_name, device_class, auth_mode, reason_class, created_at)`.

Запись событий:

- `/account/integration` failure пишет `integration_failed`;
- `/account/integration` success пишет `integration_saved`;
- `/account/integration` CSRF rejection does not write a product activation
  event. It remains a write-free security rejection and must not pollute the
  integration failure funnel.
- `/account/integration/reauth` не пишет activation event: reauth belongs to
  established accounts and must not pollute new-account activation funnel;
- `/account/telemetry/token-copied` пишет `token_copied`.
- Event writes are best-effort and must never fail/rollback the user-facing
  account route. Insert failure logs a bounded warning and the original route
  response continues.
- `device_class` is derived server-side from request headers by coarse allowlist
  bucketing only: `mobile` if lower-cased User-Agent contains common mobile
  markers (`mobile`, `android`, `iphone`, `ipad`), `desktop` if User-Agent is
  present but no mobile marker matches, and `unknown` if header is missing or
  classification fails. Raw User-Agent is never persisted or exported.
- `reason_class` mapping: `AuthError` → `auth_error`,
  `HostResolutionError` → `host_resolution_error`,
  `VetmanagerError` → `vetmanager_error`, `ValueError` validation paths after
  CSRF has passed → `validation_error`, anything else → `unknown`.

Retention/window:

- Funnel horizon: accounts with `created_at >= now - 30 days`.
- Event aggregation horizon: events with `created_at >= now - 30 days` joined
  to accounts with `Account.created_at >= now - 30 days`; older account events
  do not appear in new-account activation panels.
- Cleanup policy: delete `activation_events` older than 90 days via explicit
  helper/script and a throttled once-per-day best-effort cleanup hook called
  from activation event writes and from `scan_activation_telemetry`; no
  user-facing flow depends on cleanup success.
- Retention lag is logged with bounded fields if cleanup fails.
- Events are append-only attempts. Repeated submit/copy can create more rows,
  but account-funnel/event gauges count distinct `account_id` per bounded label
  tuple, so repeated retries do not inflate account counts.

Prometheus:

- расширить `vetmanager_activation_funnel_accounts{stage=...}` stages:
  `new_registered`, `integration_saved`, `token_issued`, `token_copied`,
  `first_mcp_request`, plus existing compatibility stages where безопасно.
  These are account-state gauges for new accounts and may be hierarchical.
- Add `vetmanager_activation_event_accounts{event,device,auth_mode,reason}`
  DB-derived gauge for distinct account counts in the 30-day new-account
  horizon. It is not named `_total` because the scan result is a snapshot and
  can decrease after retention/window expiry.
- Failure visibility is provided by `vetmanager_activation_event_accounts` and
  Grafana breakdown panels, not by mixing non-state failures into the
  account-state funnel gauge.
- `/metrics` scan uses aggregate SQL `GROUP BY` over bounded 30-day window and
  indexed predicates. It remains behind metrics auth and best-effort. Existing
  timeout guard for activation scan remains the safety boundary.
- Activation scan may reuse a process-local cached snapshot for up to 60 seconds
  to avoid repeated DB aggregation if Prometheus/Grafana scrape more often than
  expected. Tests cover cache expiry/reset.
- Backward compatibility: existing stages `registered`, `connected`,
  `with_active_tokens`, `ready_for_mcp`, `with_recent_usage_7d` remain emitted.
  New stages are additive: `new_registered`, `integration_saved`, `token_issued`,
  `token_copied`, `first_mcp_request`.
- Derived stage predicates, scoped to accounts with
  `Account.created_at >= now - 30 days`: `new_registered` = non-archived
  account in the window; `integration_saved` = active Vetmanager connection;
  `token_issued` = at least one service bearer token row; `token_copied` = at least one
  `activation_events.token_copied`; `first_mcp_request` =
  `ServiceBearerToken.last_used_at` or `TokenUsageStat.last_used_at` or
  `TokenUsageStat.request_count > 0`.
- Event breakdown semantics: `integration_failed` counts any new account that
  had at least one failed initial integration event in the 30-day window, even
  if it later succeeded. Recovery is visible because the same account can also
  contribute to `integration_saved`.
- Cardinality budget for `vetmanager_activation_event_accounts`: event names
  (3) × device classes (3) × auth modes (3) × reasons (5) = maximum 135 series.
  Any allowlist growth requires revisiting this budget.
- Cleanup scheduling is independent of the scan cache: cleanup due-check runs
  before returning a cached metrics snapshot.

Grafana:

- заменить/дополнить activation panel на funnel новых аккаунтов по
  `vetmanager_activation_funnel_accounts`;
- добавить breakdown panel for failed integration attempts by reason/device,
  without account/email/domain labels.

### Инварианты

- No secrets/PII in DB activation events except internal numeric `account_id`.
- Activation events cascade/delete with their account; retained rows never
  outlive account deletion.
- Prometheus labels are bounded and PII-free.
- `/metrics` remains best-effort: scan failure logs warning and metrics still
  render.
- Reauth does not contribute to new-account activation events.
- Existing `business_events_total` and old activation stages remain compatible
  where tests rely on them.
- `token_copied` endpoint remains session + CSRF protected.

### Rollback/fallback

If event persistence causes issues, call sites can keep structured logs and
business counters while `scan_activation_telemetry` ignores the new table. The
migration is additive; old code can run without consuming the table after
rollback. The cleanup helper can be disabled without affecting account flows.

## Architecture Critique

Required: yes. This stage changes storage, production metrics, Grafana, and
cross-module account route → telemetry boundaries.

Status: completed. Claude Opus returned 6 material findings; all accepted:

- closed `reason_class` enum is required before labels;
- reauth events must be excluded from new-account activation;
- retention and bounded scan window are required;
- aggregate scan must use indexed/grouped bounded queries;
- DB-derived event metric must be a gauge, not `_total`;
- failed integration belongs in event breakdown, not the account-state funnel
  gauge.

## Spark PRD Review

Status: completed. `gpt-5.3-codex-spark` returned 5 medium findings; accepted
and resolved in PRD:

- repeated events must not inflate account funnel — gauges count distinct
  accounts, events remain append-only attempts;
- scrape load needs a budget — add 60 second process-local scan cache;
- retention needs ownership — add daily best-effort cleanup hook and failure
  logs;
- backward compatibility must be explicit — old stages remain emitted;
- event breakdown must be scoped to new accounts — join events to account
  creation window.

## Strong PRD Review

Status: completed. Claude Opus returned 9 high/medium findings; all accepted
and resolved in PRD:

- activation event writes are best-effort and cannot break account routes;
- `device_class` derivation is server-side coarse bucketing with raw UA never
  stored;
- cleanup is also triggered from event writes and runs independently of scan
  cache;
- derived stages have exact DB predicates;
- `reason_class` mapping is explicit;
- activation events cascade with account deletion;
- fail-then-succeed semantics are explicit;
- event metric cardinality budget is 135 series.

## Декомпозиция

- 198.1 PRD/research and review gates.
- 198.2 Add migration/model/helper for bounded activation events.
- 198.3 Record integration failed/saved and token_copied events from account
  routes.
- 198.4 Extend activation telemetry scan and Prometheus rendering.
- 198.5 Update Grafana dashboard panels and dashboard tests.
- 198.6 Full tests, audit, committed diff reviews, push/deploy/prod smoke.

Each implementation subtask is expected to stay under 150 LOC or under 2 hours.

## Acceptance Criteria

- Failed initial integration attempt persists one `integration_failed` event with
  `account_id`, safe `reason_class`, `auth_mode`, `device_class`; no raw
  exception/domain/API key/login/user agent is stored.
- If activation event insert fails, `/account/integration` and
  `/account/telemetry/token-copied` still return their normal user-facing
  result and log only bounded warning fields.
- Successful initial integration persists one `integration_saved` event.
- Reauth success/failure does not persist activation events.
- Token/config copy persists one `token_copied` event and preserves existing
  `business_events_total{event="token_copied"}` behavior.
- `/metrics` exports aggregate activation funnel stages:
  `new_registered`, `integration_saved`, `token_issued`, `token_copied`,
  `first_mcp_request`.
- `/metrics` exports bounded event breakdown gauge
  `vetmanager_activation_event_accounts{event,device,auth_mode,reason}`.
- Repeated submits/copies do not inflate account-count gauges; aggregation uses
  distinct account ids per bounded label tuple.
- Existing `vetmanager_activation_funnel_accounts` labels remain emitted for
  backward compatibility.
- Tests cover fail-then-succeed account semantics: failed breakdown still shows
  the failed account, and state funnel also shows it as integrated.
- Tests cover raw User-Agent is not stored and maps only to
  `mobile`/`desktop`/`unknown`.
- Tests cover account deletion removes activation events.
- Grafana dashboard has a PII-free activation funnel panel and a failed
  integration breakdown panel.
- Activation event scan and cleanup are bounded to the configured horizons and
  covered by indexes/tests.
- Metrics scan cache avoids DB aggregation more than once per 60 seconds per
  process unless cache is reset.
- Unit tests cover event persistence, label allowlists, Prometheus output, and
  dashboard query safety.
- Full local Docker suite passes.
- Spark + Claude review gates pass before push.
- GitHub Tests and Deploy Prod are green.
- Production smoke verifies `/metrics` exposes the new activation series and
  account registration/integration/token flow still works.

### Post-review semantic clarification

The ordered Grafana new-account funnel is:

`new_registered -> integration_saved -> token_issued -> first_mcp_request`.

`token_copied` remains exported as `vetmanager_activation_funnel_accounts` and
`vetmanager_activation_event_accounts`, but it is treated as an optional UI
branch and is not part of the ordered Grafana funnel. This avoids implying that
copying the generated config is mandatory before the first MCP request.

### Production verification note

GitHub Tests run `29123674747` and Deploy Prod run `29123848025` were green for
commit `6ac151e`. The deploy script's remote post-deploy smoke verified
`/healthz`, `/readyz`, `/metrics`, `/mcp`, public `/mcp`, Prometheus target
health, and Grafana dashboard availability using server-side secrets.

Manual public smoke verified `/healthz` and `/readyz`, and a Playwright browser
smoke completed registration, invalid integration error in Russian, real test
Vetmanager integration, quick token issue, and mobile/desktop overflow checks.
The public `/metrics` endpoint correctly returned `403` without the production
metrics token; local `.env` did not contain the current production token, so
new activation series were not scraped from the operator machine after deploy.
