# PRD: Этап 57 — Deploy safety и инфраструктурная надёжность

## Цель
Предотвратить повторение потери данных и сбоев деплоя, усилить production safety.

## Контекст
- `deploy_server.sh` уже содержит pre-deploy backup, pg_isready wait, PG_VERSION check
- `post_deploy_smoke_checks.sh` проверяет /healthz, /readyz, /metrics, /mcp
- `backup_daily_cron.sh` делает ежедневные бекапы с ротацией 30 дней
- CI: test.yml → deploy-prod.yml (автодеплой после тестов на main)

## Подзадачи

### 57.1 Документировать --volumes protection
- Добавить в deploy_server.sh явный комментарий-предупреждение
- Добавить safety check: если кто-то вызывает `docker compose down -v` или `--volumes` — abort

### 57.2 Pre-deploy migration check
- Перед `alembic upgrade head` проверить `alembic current` vs `alembic heads`
- Если уже на head — skip migration, log
- Если есть pending — run upgrade, log what was applied

### 57.3 Post-deploy DB integrity smoke
- После запуска MCP добавить проверку: таблицы accounts, service_bearer_tokens существуют
- Через `docker exec postgres psql` — SELECT 1 FROM table LIMIT 0

### 57.4 Rollback script
- `scripts/rollback_db.sh` — восстановить БД из latest backup
- Опционально принимает путь к конкретному файлу бекапа

### 57.5 CI test для deploy scripts
- Добавить shellcheck в CI workflow
- Dry-run validation (syntax check) для всех .sh скриптов

### 57.6 AssumptionLog
- Записать решения и допущения этапа
