# PRD Этап 206: Vetmanager host resolution resilience

## Контекст

Production feedback reports `#26`-`#35` от `2026-07-17` образуют один кластер:
MCP runtime не смог резолвить или достучаться до Vetmanager host до выполнения
бизнес-запросов. Затронуты read-only сценарии:

- `get_clients` для CRM/missed-call/Mango STT проверок;
- `get_cassa_closes` для finance reconciliation;
- `get_medical_cards_by_date` и `get_daily_schedule` для расписания и медкарт.

Все 10 reports остались `new`, без `known_issue_id`. Часть reports содержит
`possible_pii=true`, но сохранённые поля уже sanitized placeholders
`<phone>`, `<client>`, `<patient>`.

Сервис на `2026-07-20` отвечает `/healthz` и `/readyz`, а свежий billing-api
lookup для tenant возвращал `HTTP 200`. Значит кластер мог быть transient, но
текущая диагностика не отделяет:

- timeout/DNS failure самого `billing-api.vetmanager.cloud`;
- успешный billing lookup, но DNS/connect timeout resolved clinic host;
- container-only DNS/network issue, когда host shell работает;
- upstream outage конкретного Vetmanager tenant.

## Цель

Сделать host-resolution и upstream-connectivity failures понятными,
наблюдаемыми и пригодными для операторского triage, не раскрывая API keys,
bearer tokens, raw clinic data, full request payloads или PII.

## Объём

- Исследовать current path:
  `domain_validation.py` → `runtime_auth.py` → `VetmanagerClient._resolve_host`
  → `host_resolver.resolve_vetmanager_host` → Vetmanager API request loop.
- Разделить причины ошибок в коде/логах/метриках без string parsing: для
  `billing_api` — `connect_timeout`, `read_timeout`, `timeout`,
  `connect_error`, `network_error`, `http_4xx`, `http_5xx`, `malformed_response`,
  `invalid_origin`; для `vetmanager_api` — `connect_timeout`, `read_timeout`,
  `timeout`, `connect_error`, `network_error`, `http_4xx`, `http_5xx`.
- `httpx.ConnectError` остаётся общим `connect_error`: DNS и connection-refused
  невозможно надёжно различить только по типу `httpx` exception. Отдельного
  DNS label не вводим.
- Порядок typed classification фиксирован и одинаков для billing/client
  transport paths: `ConnectTimeout` → `connect_timeout`; `ReadTimeout` →
  `read_timeout`; другой `TimeoutException` → `timeout`; `ConnectError` →
  `connect_error`; другой `RequestError` → `network_error`. Классификатор
  использует только `isinstance`, без текста исключения или его cause.
- Добавить operator-safe structured logs с `event_name`, `domain`, `target`,
  `reason`, `attempt`, `correlation_id`, но без resolved URL path, credentials
  и request body.
- Correlation ID из inbound MCP request передаётся неизменным в billing
  resolver и Vetmanager API requests; если HTTP request context отсутствует,
  создаётся один ID на logical client call и используется для обеих legs.
- Добавить или уточнить Prometheus counters через existing
  `record_upstream_failure` / `record_upstream_request`, сохранив bounded label
  cardinality.
- Не использовать persistent last-known-good fallback. Existing success-only
  resolver TTL cache уже безопасно даёт повторное использование origin только
  до истечения TTL; после истечения origin всегда должен быть заново получен
  через billing API. При outage billing API невозможно доказать, что клиника
  не сменила origin, поэтому stale routing не допускается.
- Улучшить user-facing `ToolError` текст для transient network/DNS failures:
  агент должен понимать, что это не пустой результат и не ошибка параметров.

## Non-goals

- Не менять Vetmanager API contracts и CRUD tool parameters.
- Не добавлять raw DNS/HTTP diagnostics в ответы пользователю.
- Не сохранять raw Vetmanager business payloads.
- Не делать automatic retry storm или бесконечные background probes.
- Не решать DNS на уровне host/container infrastructure вручную без
  воспроизводимого evidence.

## Архитектурное решение

### Проблема

Сейчас feedback reports с разными tools и fingerprints сходятся в один
операционный симптом: MCP не может получить данные из-за host resolution или
network failure. Но оператору трудно понять, сломался billing API, resolved
clinic host, container DNS или конкретный upstream tenant.

### Контекст и ограничения

- Главный PRD требует получать base URL через
  `GET https://billing-api.vetmanager.cloud/host/{domain}` и использовать
  validated HTTPS origin.
- `domain` проходит strict subdomain validation.
- Resolved host обязан проходить allowlist-проверку Vetmanager зоны.
- В проекте уже есть `record_upstream_failure`,
  `record_upstream_request`, structured runtime logs, per-domain breaker и
  billing resolver TTL cache.
- Privacy boundary: логи/ошибки не должны раскрывать API keys, bearer tokens,
  raw business data, телефоны, имена клиентов/пациентов или request payloads.

### Варианты

1. Только создать `known_issue` для текущих reports.
   - Плюсы: быстро закрывает operator queue.
   - Минусы: не улучшает runtime диагностику; следующая DNS проблема снова
     попадёт в raw feedback без actionability.

2. Увеличить retries/timeouts.
   - Плюсы: может скрыть transient DNS failure.
   - Минусы: ухудшает latency, может усилить upstream pressure, не объясняет
     причину и не помогает отличить host/container/Vetmanager outage.

3. Классифицировать failure path и добавить bounded diagnostics без stale
   fallback.
   - Плюсы: минимальный blast radius, совместимо с existing observability,
     улучшает triage и не меняет API contract.
   - Минусы: не гарантирует автоматическое восстановление при каждом DNS
     outage.

Выбор: вариант 3. Existing TTL cache сохраняется как единственный bounded
fallback до истечения TTL; persistent last-known-good origin не реализуется.

### Инварианты

- Runtime после истечения resolver TTL продолжает получать clinic origin через
  billing API; stale origin не используется.
- Любой billing-resolved origin проходит `validate_resolved_vetmanager_origin`.
- Labels в Prometheus остаются low-cardinality: stage 206 использует только
  закрытые константные `target`/`reason` значения; новые target labels не
  вводятся.
- HTTP failures сворачиваются только в `http_4xx` и `http_5xx`, а не в raw
  status code labels.
- Billing failures остаются на `target="billing_api"`; resolved clinic-host
  failures остаются на существующем `target="vetmanager_api"`.
- Ошибки пользователю не содержат raw host path, credentials, PII или payloads.
- Breaker/retry поведение не создаёт retry amplification.

### Rollback/fallback

Persistent fallback исключён до реализации. Если новые labels создают шум или
cardinality risk, откатить их к существующим `target/reason` families с более
грубой причиной. Billing retry остаётся bounded: максимум одна повторная
попытка для timeout/connect/network; HTTP status не ретраится в этом этапе,
чтобы не менять latency/load контракт без production evidence. Coalescing
сохраняет одну lookup-операцию на domain для concurrent cold calls; отдельный
billing breaker или negative-cache не вводятся в этом scoped fix.

Architecture Critique: required before implementation, because task changes
production behavior, observability semantics and cross-module upstream
transport boundaries.

## Декомпозиция

| Подзадача | Оценка | Файлы |
| --- | ---: | --- |
| 206.1 Root cause PRD/research: собрать current failure path, exception taxonomy, logs/metrics inventory, принять/reject fallback | ≤2h | `host_resolver.py`, `vetmanager_client.py`, `vm_transport/*`, `service_metrics.py`, tests |
| 206.2 Failure classification: typed helpers for billing vs resolved-host connect/read/network failures | ≤2h | `host_resolver.py`, `vetmanager_client.py`, tests |
| 206.3 Observability: bounded logs/metrics and stable operator-safe ToolError hints | ≤2h | `service_metrics.py`, `observability_logging.py`, client/resolver tests |
| 206.4 Persistent last-known-good fallback — rejected by Architecture Critique; retain existing unexpired TTL cache only | ≤2h | no code change |
| 206.5 Post-fix production triage: deploy smoke, verify metrics/logs, link/resolve reports `#26`-`#35` | ≤2h | production DB via `scripts/triage_agent_feedback.py` |

## Acceptance Criteria

- Tests cover billing API connect/read/other timeout, connect/network, HTTP,
  malformed response and invalid origin classification.
- Tests cover resolved Vetmanager host connect/read/other timeout and
  connect/network failure classification separately from billing lookup.
- Logs include low-cardinality `event_name`/`reason` and correlation metadata,
  without credentials, request bodies or PII.
- Один correlation ID присутствует в logs billing resolver и Vetmanager API
  для одного logical MCP call.
- Prometheus metrics expose bounded failure reasons for billing API and
  Vetmanager API failures.
- User-facing tool error distinguishes transient connectivity from empty
  business result or invalid parameters.
- Existing successful host resolution and Vetmanager request behavior remains
  backward compatible.
- Billing HTTP error paths record both request and failure metrics; malformed
  and invalid billing payloads do not remain visible as successful `http_200`.
- Full test suite passes before merge/deploy.

## Review gates

### Spark PRD review

- Read-only launch hit the documented `bwrap` runtime failure before reading
  files; one review-only retry with `-s danger-full-access` was used.
- Accepted: missing billing HTTP metrics; typed transport taxonomy; bounded
  metrics labels at stage call sites; regression coverage.
- Accepted with a narrower solution: resolver-before-breaker is documented as
  bounded (one retry plus concurrent coalescing); a new billing breaker or
  negative cache would broaden the production behaviour without incident
  evidence.
- Final pass: rejected a separate billing negative-cache/breaker as scope
  expansion; accepted explicit ordered `httpx` subclass mapping to prevent
  ambiguous metric labels.

### Claude Opus Architecture Critique / PRD review

- Accepted: reject persistent last-known-good fallback; do not claim reliable
  DNS classification; keep resolved-host reasons under `vetmanager_api`; add
  malformed/invalid billing response metrics.
- Accepted with rationale: no billing HTTP retry in this scoped fix. Existing
  timeout/connect/network retry stays bounded; changing 5xx retry policy needs
  separate production evidence.

## Что сделать после фикса

После production deploy обязательно выполнить operational closure:

1. Run production smoke:
   - `/healthz`;
   - `/readyz`;
   - authenticated `/metrics`;
   - one MCP read-only call for the affected tenant if a safe token is
     available.
2. Confirm new/updated metrics:
   - billing API success/failure series;
   - Vetmanager API DNS/connect/read/network failure reasons;
   - no high-cardinality host/path labels.
3. Check runtime logs around smoke by `correlation_id` and verify no API keys,
   bearer tokens, phone numbers, client/patient names or raw payloads appear.
4. Run:
   `python scripts/triage_agent_feedback.py recent --limit 10`
   and confirm reports `#26`-`#35` are still the target unresolved cluster.
5. Create or update one production `known_issues` entry for this cluster with:
   - status `fixed` if deploy proves the issue is fixed;
   - status `workaround_available` if only diagnostics/workaround shipped;
   - concise public summary and agent playbook explaining transient
     connectivity vs legitimate empty result.
6. Link/resolve reports `#26`-`#35` to that known issue via
   `scripts/triage_agent_feedback.py resolve-report`.
7. Re-run product metrics and verify:
   - `feedback.reports.by_status_30d.new` decreases by 10 or those reports are
     no longer `new`;
   - `known_issue_id` is visible in `recent`;
   - `known_issue_match_events` expectations are documented if still zero.
8. Write external work log in
   `/home/otis/myprojects/LiveHelperAgent/logs/mcp/` with deploy, smoke,
   triage and linked report IDs.

## Проверки

- Targeted unit tests for resolver/client classification.
- Existing transport/retry/breaker tests.
- `docker compose --profile test run --rm test`.
- `git diff --check`.
- Spark-review PRD before implementation; Claude Opus Architecture
  Critique/PRD-review because production behavior and transport boundaries are
  affected.
