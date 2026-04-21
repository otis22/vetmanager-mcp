# PRD: Этап 128 — Final release gate и production deploy

## Цель

Завершить текущий цикл работ после этапов 122-127 формальным release gate и production deploy, не пропуская обязательные проверки, backup, smoke и post-release наблюдение.

## Контекст

- Super-review `artifacts/review/2026-04-20-full-stage-121.md` запрещает следующий release до закрытия blocker/high хвоста.
- В `Roadmap.md` этапы 122-127 фиксируют обязательные исправления перед следующим production rollout.
- `artifacts/release-checklist-vetmanager-mcp-ru.md` и `artifacts/operations-readiness-vetmanager-mcp-ru.md` уже задают pre-release, pre-deploy и post-deploy требования.
- Пользовательское требование на этот цикл: deploy должен быть в конце, а не как параллельная activity.

## Scope

Этап включает только release-management и production rollout:
- подтверждение готовности хвоста 122-127;
- полный regression run;
- pre-deploy backup и rollback point;
- production deploy через canonical scripts;
- post-deploy smoke и короткое post-release наблюдение;
- фиксацию результата в артефактах проекта.

Этап не включает:
- новые feature/fix изменения вне 122-127;
- отдельный refactor или cleanup после deploy;
- расширение release checklist beyond current artifacts.

## Декомпозиция

### 128.1 Release readiness sync (≤30 мин, без кодовых изменений)

- Проверить, что этапы 122-127 закрыты в `Roadmap.md`
- Проверить синхронность `Roadmap.md`, `PRD/`, `AssumptionLog.md`
- Убедиться, что release/review artifacts не содержат явного drift перед rollout

### 128.2 Regression gate (≤2 ч, без prod-изменений)

- Прогнать `docker compose --profile test run --rm test`
- Если в предыдущих этапах затронуты browser/real контуры, прогнать релевантные opt-in проверки
- Зафиксировать, что release gate зелёный до deploy

### 128.3 Pre-deploy safety checks (≤1 ч, без кодовых изменений)

- Проверить production secrets/env и migration plan
- Проверить, что deploy идёт production target/profile
- Подготовить rollback point согласно operations readiness

### 128.4 Backup и deploy (≤1 ч, ≤20 строк сопроводительных правок при необходимости)

- Выполнить pre-deploy backup PostgreSQL
- Запустить `scripts/deploy_server.sh` или `scripts/sync_and_deploy_server.sh`
- Не делать дополнительных code changes в этом подпроцессе без возврата в отдельный stage

### 128.5 Post-deploy smoke и release closeout (≤1 ч, без feature-изменений)

- Прогнать `scripts/post_deploy_smoke_checks.sh`
- Проверить `/healthz`, `/readyz`, `/metrics`, `/mcp`
- Проверить web flow `landing -> login -> account`
- Проверить MCP call существующим bearer token
- Зафиксировать release outcome, rollback point и commit SHA в `AssumptionLog.md`

## Верификация

- `docker compose --profile test run --rm test`
- Production deploy выполнен через canonical script
- `scripts/post_deploy_smoke_checks.sh`
- Ручная проверка web flow и bearer-backed MCP call

## Риски

- Если regression gate не зелёный, deploy откладывается без исключений
- Если backup/rollback point не подтверждён, deploy не выполняется
- Если post-deploy smoke падает, этап не закрывается до rollback или исправления с новым полным прогоном проверок
