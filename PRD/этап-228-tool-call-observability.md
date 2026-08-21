# Этап 228. Наблюдаемость вызовов инструментов

## Цель

Дать оператору total tool calls за выбранный Grafana range, time series по
tool и год истории Prometheus; отсутствие account-age series должно оставаться
No data.

## Декомпозиция

1. Добавить две панели и layout/test assertions (до 150 строк).
2. Изменить retention и No-data query, проверить compose/dashboard (до 50 строк).

## Архитектурное решение

Панели используют уже существующий low-cardinality counter
`vetmanager_tool_calls_total`: `sum(round(increase(...[$__range])))` для stat
(целочисленная operational estimate, корректная для counter reset) и
`sum by (tool) (increase(...[$__rate_interval]))` для истории. Это не вводит новые
labels или storage. Retention меняется с 30d на 365d при существующем size cap
1GB. `or vector(0)` удаляется только у age-panel, где zero semantically false.

Варианты: новый metric/recording rule (лишний runtime surface) либо existing
counter expressions (выбран). Базовая capacity-проверка: 30 days занимают
19MB, годовая линейная оценка около 231MB — существенно ниже 1GB; 365d остаётся
best-effort, поскольку size cap может сработать раньше при росте series; после deploy
operator verifies TSDB retention config and available disk (13GB). Инварианты: no PII labels; size cap остаётся;
dashboard IDs/layout уникальны; empty age metric shows Grafana No data.
История до deploy не восстанавливается: первые 11 месяцев range будут частично
пустыми. Rollback: revert JSON/compose, deploy/restart Prometheus, then verify its
effective retention flags and dashboard provisioning; size cap remains active.

Architecture Critique: required — production observability/storage retention.

## Acceptance criteria

1. Dashboard has `Total tool calls in range` stat and per-tool time series.
2. Prometheus retention is `365d`, size cap is `1GB`.
3. Account-age expressions do not contain `or vector(0)`.
4. Static tests verify expressions, titles and safe labels.
