# PRD — Этап 212: корректность activation dashboard и product report

## Статус

Done; local checks and committed-diff review passed. Push/remote CI is tracked
in the release record.

## Цель

Устранить две вводящие в заблуждение агрегации: Grafana должна отделять
persisted product events от вычисляемых стадий воронки, а top accounts в
30-дневном отчёте должны отражать тот же 30-дневный период.

## Проверенные факты

- `storage_models.ACTIVATION_EVENT_NAMES` и DB constraint допускают только
  `integration_failed`, `integration_saved`, `token_copied`.
- `vetmanager_activation_event_accounts` экспортирует эти persisted events;
  `token_issued` и `first_mcp_request` вычисляются отдельно в
  `vetmanager_activation_funnel_accounts{stage=...}`.
- Панель `Activation events` сейчас фильтрует event-метрику по
  `integration_failed|token_issued|first_mcp_request`, поэтому две стадии
  никогда не совпадут с label `event`.
- `TokenUsageStat.request_count` — lifetime-счётчик. Успешные request события
  с timestamp хранятся в `TokenUsageLog` как `token_auth_succeeded`.
- Отчёт уже маркирован fixed 30-day window и его `requests.total_30d` считает
  именно `TokenUsageLog` за 30 дней.

## Scope и декомпозиция

### 212.2 Dashboard event/funnel separation (≤ 30 строк)

- Заменить filter панели на полный persisted allowlist.
- Не добавлять synthetic event names в storage и не смешивать funnel stages с
  event labels.
- Добавить JSON regression test, который проверяет allowlist панели и отдельный
  funnel query для `token_issued`/`first_mcp_request`.

### 212.3 Windowed top accounts (≤ 70 строк)

- Получать top accounts по `TokenUsageLog.token_auth_succeeded` с
  `event_at >= now - 30 days`, join через token к non-archived account.
- Явно назвать таблицу Markdown `Top accounts (30d)` и label requests
  `requests_30d`.
- Добавить детерминированный regression test с `--now-override`: старый
  lifetime-heavy account не должен обгонять новый активно используемый.
- Проверить все sections report: counters 24h/7d/30d, failures, feedback и
  known issue sections carry their period in key/header. Time-window counters
  use the same half-open `[now - window, now)` boundary; lifetime account/token
  inventory и dead-account status are labelled as state, not period aggregate.

### 212.4 Quality gates

- Targeted tests, JSON validation, fast/full Docker tests.
- Audit, Spark + Claude Opus diff review, commit, push, remote GitHub CI.

## Архитектурное решение

### Проблема и ограничения

Нельзя делать dashboard корректным расширением `ActivationEvent`: это изменит
product telemetry/storage contract ради визуализации. Нельзя получать
historical 30-дневный ranking из `TokenUsageStat`, поскольку timestamp
`last_used_at` не распределяет накопленный счётчик по периоду.

### Рассмотренные варианты

1. Добавить `token_issued`/`first_mcp_request` в `ActivationEvent` и оставить
   существующий panel filter. Отклонён: меняет semantics и не создаёт честную
   историческую запись для уже существующих accounts.
2. Оставить top accounts lifetime и переименовать section. Допустимо, но
   ухудшает главный purpose 30-day report и не согласуется с `total_30d`.
3. Использовать уже существующие раздельные источники: event allowlist для
   панели, funnel metric для стадий, timestamped successful audit logs для
   ranking. Выбрано.

### Выбранное решение и инварианты

`Activation events` отображает все и только persisted event labels.
`Activation funnel` остаётся единственным местом для `token_issued` и
`first_mcp_request`. Top accounts отображают число successful auth/request
events в полуоткрытом 30-day окне `[now - 30d, now]`; archived accounts
исключаются. Отчёт не пишет в БД и сохраняет masked email output.

### Rollback/fallback

Изменения additive и read-only. Если event audit log перестанет быть
достаточным источником request history, ranking можно временно удалить из
отчёта; нельзя возвращаться к lifetime counter под 30-day label.

## Architecture Critique

Required: задача меняет read-side границу storage/observability и публичный
операционный смысл 30-day report. До реализации нужна внешняя критика
выбранного источника данных и backward compatibility.

## Acceptance criteria

1. Dashboard panel has no nonexistent `event` filters; funnel stages query
   `vetmanager_activation_funnel_accounts` separately.
2. A fixed `--now-override` test proves a pre-window lifetime-heavy account is
   excluded while an in-window active account ranks first.
3. Markdown header/column name makes 30-day ranking explicit.
4. JSON, targeted and full required checks pass; review, commit, push and CI
   are green.
