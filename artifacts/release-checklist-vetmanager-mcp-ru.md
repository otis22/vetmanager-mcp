# Release Checklist: vetmanager-mcp

Обновлено: 2026-03-27

## Перед merge / release

- [ ] все roadmap/PRD/AssumptionLog артефакты синхронизированы
- [ ] default contour зелёный (`docker compose --profile test run --rm test`)
- [ ] если менялись browser/real контуры, их impact оценён отдельно
- [ ] если менялись secrets/auth/security paths, обновлены deployment notes
- [ ] если менялись MCP tools/prompts, проверить tools/list schema test
- [ ] security review: нет утечек секретов в логах, ошибках, UI

## Перед deploy

- [ ] pre-deploy backup PostgreSQL выполнен и rollback point зафиксирован (`scripts/backup_postgres.sh` или backup step внутри `deploy_server.sh`)
- [ ] проверено наличие нужных env secrets (`STORAGE_ENCRYPTION_KEY`, `WEB_SESSION_SECRET`)
- [ ] если есть schema changes, подтверждён Alembic migration plan
- [ ] если есть breaking auth/session change, согласовано maintenance window
- [ ] Docker build использует `--target production` (не test)

## После deploy

- [ ] `scripts/post_deploy_smoke_checks.sh` прошёл успешно
- [ ] `/healthz` отвечает 200
- [ ] `/readyz` стабильно 200
- [ ] `/metrics` scrape проверен по текущему контракту: без auth при пустом `METRICS_AUTH_TOKEN`, либо с `Authorization: Bearer <METRICS_AUTH_TOKEN>` когда gate включён
- [ ] PostgreSQL после deploy доступен; backup artifact/rollback point сохранён и миграции применились без ошибок
- [ ] error tracking bootstrap ведёт себя ожидаемо

## После release

- [ ] проверить logs по `runtime` / `security` / `audit`
- [ ] проверить отсутствие всплеска `vetmanager_upstream_failures_total`
- [ ] проверить отсутствие всплеска auth failures
- [ ] проверить доступность web UI: landing → login → account
- [ ] проверить что существующие bearer tokens работают (MCP call)
