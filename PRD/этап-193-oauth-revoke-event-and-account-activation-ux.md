# Этап 193. OAuth revoke event and account activation UX

## Контекст

`web_routes_account.py` already records `record_business_event("oauth_grant_revoked")`
when a ChatGPT/OAuth connection is disconnected, but `service_metrics.py`
strict allowlist does not include this event. As a result, the event is logged as
unknown and never appears in `vetmanager_business_events_total`.

Пользователь также показал account onboarding panel, где checklist частично на
английском и шаг "MCP client made at least one request" остаётся неготовым,
хотя запросы у пользователя уже были. Current UI uses recent `last_used_at`
only; account dashboard already has `request_count` from `TokenUsageStat`.

## Цель

1. Сделать OAuth/ChatGPT disconnect видимым в business events metrics.
2. Исправить account onboarding checklist: считать MCP-клиент использованным,
   если у любого usable active token row в account dashboard есть
   `request_count > 0` или любой `last_used_at`.
3. Перевести checklist на русский и проверить, что верстка не поехала.
4. После deploy проверить production: registration/account flow, metrics,
   Grafana/business events, and visual layout.

## Scope

- Add fixed low-cardinality event `oauth_grant_revoked` to
  `_ALLOWED_BUSINESS_EVENTS`.
- Keep unknown business events rejected/logged.
- Keep revoke semantics unchanged: account disconnect still revokes the whole
  grant/access/refresh token family. The route records the business event only
  when the grant itself transitions to revoked; child-token repair under an
  already-revoked grant is a structured log only, and pure repeat no-op
  disconnects do not increment the counter.
- Change only account activation UX copy/state calculation; no token/auth scope
  changes.
- Verified Grafana `Business events` panel uses
  `sum by (event) (increase(vetmanager_business_events_total[1h]))` and
  `{{event}}` legend, so it auto-picks the new fixed event value with no
  dashboard event enumeration.
- No PII in Prometheus/Grafana labels.

## Acceptance

- `record_business_event("oauth_grant_revoked")` increments
  `business_events_total` and Prometheus exposes
  `vetmanager_business_events_total{event="oauth_grant_revoked"}`.
- An unknown event such as `oauth_bogus` remains rejected/logged and does not
  appear in `business_events_total`.
- OAuth disconnect route no longer emits unknown-event error for this event.
- Account activation panel is fully Russian for checklist rows.
- Account activation panel marks "MCP client used" done when any token view row
  for a currently usable token has `request_count > 0` or any `last_used_at`,
  even if that usage is stale. Here `request_count` is success-only for bearer
  runtime auth/context resolution: failed auth attempts do not increment it.
  Historical usage on a revoked/expired token does not mark a fresh unused token
  as ready. `request_count` is per-token from `TokenUsageStat.bearer_token_id`,
  joined in `web.py::_load_account_dashboard` into the token view as
  `request_count`.
- Account route regression covers the real dashboard loader path: a
  `TokenUsageStat` row with `request_count > 0` and no `last_used_at` renders
  the activation panel as ready.
- Automated tests assert no residual English checklist labels and existing
  viewport/layout test passes with the Russian copy. The copy test checks
  concrete old English phrases, not legitimate acronyms such as MCP, ChatGPT or
  OAuth.

## Deploy verification

- After production deploy, verify `/metrics` exposes
  `oauth_grant_revoked` after a real ChatGPT/OAuth disconnect.
- Verify registration/account flow, including account activation panel layout,
  with browser/screenshot or equivalent visual check.

## Simplicity

This is a narrow fix: one allowlist entry, localized copy, and one helper
predicate. No new abstraction, schema, DB migration, or Grafana panel is needed.
