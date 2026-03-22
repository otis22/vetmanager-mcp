# Release Checklist: vetmanager-mcp

## Перед merge / release

- все roadmap/PRD/AssumptionLog артефакты синхронизированы
- default contour зелёный
- если менялись browser/real контуры, их impact оценён отдельно
- если менялись secrets/auth/security paths, обновлены deployment notes

## Перед deploy

- создан backup storage
- проверено наличие нужных env secrets
- если есть schema changes, подтверждён migration plan
- если есть breaking auth/session change, согласовано maintenance window

## После deploy

- `scripts/post_deploy_smoke_checks.sh` прошёл успешно
- `/metrics` scrape доступен
- `/readyz` стабильно `200`
- error tracking bootstrap ведёт себя ожидаемо

## После release

- проверить logs по `runtime` / `security` / `audit`
- проверить отсутствие всплеска `vetmanager_upstream_failures_total`
- проверить отсутствие всплеска auth failures
