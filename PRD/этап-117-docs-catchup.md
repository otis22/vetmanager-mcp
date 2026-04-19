# Этап 117. Docs catchup

## Цель

Устранить drift technical-requirements (14 этапов) + observability runbook + README obs section из super-review T4. Добавить `(pending)` check в workflow script.

## Scope

### 117.1 technical-requirements updates

`artifacts/technical-requirements-vetmanager-mcp-ru.md` — append stage-history block для этапов 97-116 с 1-line описаниями; добавить `scripts/`, `.claude/commands/` в structure; упомянуть business_events_total, product_metrics_report, billing resolver cache.

### 117.2 observability runbook

`artifacts/observability-runbook-vetmanager-mcp-ru.md` — добавить секцию с stage-88 (`vetmanager_upstream_requests_total`, `vetmanager_tool_calls_total`) и stage-110 (`vetmanager_business_events_total`) метриками + banner "Last updated: stage N" если полная ревизия отложена.

### 117.3 README Observability section

README.md:129-139 — добавить bullet `vetmanager_business_events_total{event=...}`.

### 117.4 workflow-check script: `(pending)` detector

`scripts/review_workflow_check.sh` — добавить check 11: для последних 5 `## Этап` секций в AssumptionLog проверить что `**Commit**:` не `(pending)`.

### 117.5 Super-review report — resolution note

`artifacts/review/2026-04-19-changed-105-110-stage-110.md` — добавить в конце "## Resolution" секцию: closed by stages 111-116; link to each commit.

## Non-scope

- CLAUDE.md self-attestation checklist updates — текущая версия достаточна.
- Perfect rewrite technical-requirements — only append changelog for 97-116, не полная перекройка.

## Acceptance

1. technical-requirements содержит stage-block для 97-116 (compact).
2. observability-runbook упоминает все 3 новые counter's (stage 88 + stage 110).
3. README obs section упоминает `vetmanager_business_events_total`.
4. `./scripts/review_workflow_check.sh 117` НЕ возвращает `(pending)` findings.
5. Super-review report имеет Resolution section.
6. Все 703 тестов зелёные; 1 новый тест на workflow-check scenario.
