# Этап 194. Analytics defaults and activation funnel

## Контекст

Свежие product metrics показывают activation gap: часть аккаунтов не доходит до
Vetmanager connection, часть не выпускает token, а среди ready-for-MCP аккаунтов
мало recent usage. Для Report AI текущий `read_only` default недостаточен:
`save_report_ai_job_as_report` требует `report_ai.write`, который входит в
preset `report_ai` с UI label `Analytics`.

В `support-bot-base` есть актуальная Vetmanager help статья:
`Integratsiya_so_storonnimi_programmami_i_servisami_cherez_REST_API.md`.
Она подтверждает путь получения REST API key: `Настройки` →
`Интеграция с сервисами` → включить функцию → редактирование → скопировать
`API KEY`, с предупреждением о широких правах.

## Цель

1. Сделать `Analytics` default access preset для ручного service bearer token
   в `/account`.
2. Сделать `Analytics` default consent preset для ChatGPT OAuth.
3. Добавить короткую подсказку в account UI, где взять Vetmanager REST API key.
4. Добавить безопасные aggregate activation funnel gauges в Prometheus/Grafana.

## Scope

- Меняем только defaults и UI copy; существующие token scopes, preset bundles,
  runtime enforcement and OAuth narrowing semantics не меняем.
- `full_access` по-прежнему требует explicit confirmation.
- Grafana получает только aggregate counts без `account_id`, email, domain,
  token prefix или других персональных/секретных labels.
- Activation funnel gauges считаются aggregate stage counts:
  `with_active_tokens` показывает active accounts with live service bearer
  tokens, а `ready_for_mcp` дополнительно требует active Vetmanager connection.
  Это делает видимыми stale-token/no-connection gaps без персональных labels.

## Acceptance

- Blank `/account/tokens` POST выпускает token со scopes
  `TOKEN_PRESET_SCOPES[PRESET_REPORT_AI]`.
- Account token form и ChatGPT OAuth consent показывают `Analytics` selected по
  умолчанию.
- OAuth full-scope request без ручной смены preset narrows to `report_ai`
  preset scopes and persists `access_preset=report_ai`.
- Account UI содержит краткие шаги получения Vetmanager REST API key.
- `/metrics` после auth отдаёт
  `vetmanager_activation_funnel_accounts{stage="..."}` для стадий:
  `registered`, `connected`, `with_active_tokens`, `ready_for_mcp`,
  `with_recent_usage_7d`.
- Grafana dashboard содержит activation funnel panel на этих gauges.
