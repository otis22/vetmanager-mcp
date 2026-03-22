## Цель этапа 47

Довести проект до более зрелого production baseline на уровне operational
процедур, release discipline и post-deploy проверок.

## Подзадачи

### 47.1 Backup/restore
- Зафиксировать стратегию резервного копирования для storage.
- Описать восстановление для sqlite и postgres вариантов.

### 47.2 Secret rotation
- Описать rotation policy для:
  - `WEB_SESSION_SECRET`
  - `STORAGE_ENCRYPTION_KEY`
  - `ERROR_TRACKING_DSN`
  - service bearer tokens

### 47.3 Migration/rollback
- Описать порядок применения миграций и rollback boundaries.

### 47.4 Post-deploy smoke checks
- Добавить автоматизируемый smoke script.
- Подключить его к deploy flow.

### 47.5 Release checklist
- Зафиксировать release checklist для изменения runtime/security/ops контуров.

### 47.6 SLO/SLA и alerting thresholds
- Зафиксировать минимальный production baseline для health, latency и upstream failures.

### 47.7 Doc sync
- Обновить README и AssumptionLog.

## Критерии готовности

- В репозитории есть ops artifact с backup/restore, rotation, migration/rollback.
- В репозитории есть release checklist artifact.
- Deploy flow использует post-deploy smoke script.
- README и AssumptionLog синхронизированы.
