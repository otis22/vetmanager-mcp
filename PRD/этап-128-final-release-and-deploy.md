# PRD: Этап 128 — Final release gate и production deploy

## Цель

Завершить текущий цикл работ после закрытия всех актуальных pre-release этапов формальным release gate и production deploy, не пропуская обязательные проверки, backup, smoke и post-release наблюдение.

## Контекст

- Super-review `artifacts/review/2026-04-20-full-stage-121.md` запрещает следующий release до закрытия blocker/high хвоста.
- В `Roadmap.md` production rollout должен идти только после закрытия всех актуальных pre-release этапов этого цикла, включая follow-up cleanup после review и token/privacy hardening.
- `artifacts/release-checklist-vetmanager-mcp-ru.md` и `artifacts/operations-readiness-vetmanager-mcp-ru.md` уже задают pre-release, pre-deploy и post-deploy требования.
- Пользовательское требование на этот цикл: deploy должен быть в конце, а не как параллельная activity.

## Scope

Этап включает только release-management и production rollout:
- подтверждение готовности актуального release хвоста в `Roadmap.md`;
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

### 128.1 Release readiness sync

- Проверить, что все pre-release этапы перед `128` закрыты в `Roadmap.md`
- Проверить синхронность `Roadmap.md`, `PRD/`, `AssumptionLog.md`
- Убедиться, что release/review artifacts не содержат явного drift перед rollout

### 128.2 Regression gate

- Прогнать `docker compose --profile test run --rm test`
- Если в предыдущих этапах затронуты browser/real/auth/metrics контуры, прогнать релевантные opt-in проверки
- Зафиксировать, что release gate зелёный до deploy

### 128.3 Pre-deploy safety checks

- Проверить production secrets/env и migration plan
- Проверить, что deploy идёт production target/profile
- Подготовить rollback point согласно operations readiness

### 128.4 Backup и deploy

- Выполнить pre-deploy backup PostgreSQL
- Запустить `scripts/deploy_server.sh` или `scripts/sync_and_deploy_server.sh`
- Не делать code changes в этом подпроцессе; если найден blocker, rollout останавливается и открывается отдельный stage/fix path

### 128.5 Post-deploy smoke и release closeout

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
- Если post-deploy smoke падает, этап не закрывается до rollback или исправления через отдельный fix-stage с новым полным прогоном проверок
