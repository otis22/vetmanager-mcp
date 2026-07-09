# Stage 189. Activation and onboarding follow-up

## Контекст

Production product metrics на 2026-07-09 показывают: 11 accounts total, 1 live
за 7 дней, 6 accounts без tokens, 5 без active Vetmanager connection. Все
feedback reports за 30 дней linked, поэтому главный сигнал здесь не runtime
bug, а слабая activation funnel.

## Цель

Сделать следующий шаг в `/account` очевидным и добавить read-only activation
funnel в product metrics. Не менять auth, token issuance, OAuth grants, scopes,
runtime resolver или Vetmanager write paths.

## Архитектурное решение

Проблема: владелец аккаунта видит разрозненные блоки integration/tokens/ChatGPT,
но не получает компактного статуса "что сделать дальше"; owner видит только
ad-hoc counts no tokens/no active connection, без funnel.

Ограничения:
- secrets не показывать: API key, raw bearer token после выдачи, user password,
  OAuth token data;
- account UI уже рендерится в `web_html.render_account_page`;
- dashboard data already loaded in `web._load_account_dashboard`;
- product metrics uses read-only SQL and masks email.

Варианты:
- отдельная admin dashboard page: лучше для owner, но больше routing/auth/UI
  scope;
- расширить existing `/account` and product metrics: меньше blast radius.

Выбор: расширить existing account page и `scripts/product_metrics_report.py`.
UI получает status/checklist из уже загруженных counts/health/tokens/grants.
Product metrics считает aggregates по existing storage tables.

Инварианты:
- token form остаётся disabled пока нет active healthy integration;
- raw secrets не попадают в HTML кроме one-time issued token panel;
- no DB migrations;
- product metrics remains owner-local and masks account emails.

Rollback: revert UI/metrics formatting changes; auth/runtime data remains
unchanged.

Architecture Critique: required because this touches production web behavior and
metrics semantics.

## Scope

1. Add compact activation checklist/status block to `/account`.
2. Add funnel aggregates to product metrics JSON/Markdown.
3. Add regression tests and viewport/layout coverage.

## Activation funnel formulas

All counts are over non-archived accounts. Counts are intentionally
hierarchical/overlapping, not mutually exclusive, unless stated otherwise.
All time comparisons use UTC-aware `now`, matching
`scripts/product_metrics_report.py` existing 30-day window behavior.

Canonical usable-token predicate:
`ServiceBearerToken.status == active AND (expires_at IS NULL OR expires_at > now)`.

- `connected`: account has at least one active `VetmanagerConnection`.
- `with_tokens`: account has at least one service bearer token in any status.
- `with_active_tokens`: account has at least one usable service bearer token.
- `with_recent_usage`: account has at least one `TokenUsageStat.last_used_at`
  with `last_used_at >= now - 7 days`, joined through `ServiceBearerToken` to
  the account. `TokenUsageStat.last_used_at` is already used by existing
  product metrics live/dead account calculations.
- `ready_for_mcp`: account has an active Vetmanager connection and at least one
  usable service bearer token. This means the account is technically ready for a
  bearer-token MCP client; it may still have zero recent usage.
- `needs_connection`: account has no active Vetmanager connection.
- `needs_token`: account has an active Vetmanager connection but no usable
  service bearer token.
- `needs_client_use`: account is `ready_for_mcp` but has no recent usage in the
  last 7 days.

The account UI uses the same conceptual ordering for the primary next step:
connection first, then active token, then MCP client usage, then all-set.

## Out of scope

- Email reminders, cron, billing/customer outreach.
- Changing token issuance, OAuth scope selection or integration save flow.
- Archiving/deleting dead accounts.

## Acceptance Criteria

1. New accounts with no integration see a clear next step to connect Vetmanager.
2. Connected accounts with no tokens see a clear next step to issue a token.
3. Accounts with active token but no recent usage see "connect an MCP client" guidance.
4. Ready accounts show an all-set state without blocking existing forms.
5. Product metrics JSON/Markdown include activation funnel aggregates.
6. HTML has stable `data-testid` selectors and does not overflow common mobile
   and desktop viewports.
7. Tests assert account HTML and activation metrics do not expose raw API keys,
   raw bearer tokens outside the existing one-time issued-token panel, passwords
   or unmasked account emails.

## Tests

- Unit HTML render tests for no integration / no token / no usage / ready states.
- Product metrics seeded DB regression for funnel counts.
- Playwright viewport test for account page after status block.
- Privacy regression assertions for no secret-like values in normal account HTML
  and masked-only emails in product metrics output.

## Review notes

- Spark PRD review 2026-07-09: accepted two findings.
  - Added canonical activation funnel formulas and explicit 7-day recent usage
    window.
  - Added executable privacy/redaction acceptance and test requirements.
- Claude Opus Architecture/PRD review 2026-07-09: accepted three findings.
  - Reconciled Roadmap aggregate list with PRD formulas.
  - Cited `TokenUsageStat.last_used_at` as the source for recent usage and
    specified UTC boundary handling.
  - Defined a single usable-token predicate and reused it across formulas.

## Rollout

Deploy with normal production flow. Post-deploy smoke: landing, login, account
render, `/metrics`, `/mcp`; visual screenshot check for account page.
