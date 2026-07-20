# PRD Этап 205: Grafana metrics dashboard

## Контекст

Пользователь попросил собрать дополнительный дашборд метрик в Grafana после
открытия production Grafana через SSH tunnel.

## Цель

Расширить provisioned dashboard `Vetmanager MCP Overview`, чтобы оператор сразу
видел HTTP, MCP tool calls, upstream Vetmanager, auth/OAuth/product counters,
cache и activation telemetry.

## Объём

- Обновить `ops/grafana/dashboards/vetmanager-overview.json`.
- Использовать только уже экспортируемые Prometheus метрики.
- Сохранить тот же dashboard UID `vetmanager-mcp-overview`, чтобы Grafana
  обновила существующий dashboard через provisioning.
- Проверить JSON и production загрузку dashboard после deploy.

## Acceptance Criteria

- Dashboard JSON валиден.
- Dashboard содержит секции Service, HTTP, MCP Tools, Upstream Vetmanager,
  Auth/OAuth/Product, Cache, Activation.
- Production Grafana после deploy отдаёт dashboard `vetmanager-mcp-overview`
  через API.
