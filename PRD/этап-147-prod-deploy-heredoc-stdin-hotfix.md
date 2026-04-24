# Этап 147. Prod deploy heredoc stdin hotfix

## Контекст

После успешного `Deploy Prod` лендинг на `https://vetmanager-mcp.vromanichev.ru/` продолжал отдавать старый HTML без блока `#mcp-agent-instructions`. Логи workflow показали, что deploy доходил до `compose run --rm mcp alembic upgrade head`, но не выполнял последующие шаги `Starting MCP service`, health check и smoke checks.

## Проблема

`docker compose run` внутри SSH heredoc может читать stdin. Без `-T` команда миграций способна забрать остаток heredoc, из-за чего удалённый deploy завершается до перезапуска MCP-сервиса, а GitHub Actions всё равно показывает success.

## Требования

- Запуск миграций в deploy script не должен читать stdin из heredoc: `-T` отключает pseudo-TTY, `</dev/null` явно закрывает stdin.
- После миграций deploy обязан выполнять `compose up -d --force-recreate --no-build mcp`.
- Smoke checks должны оставаться частью deploy path.
- Тест должен фиксировать `-T` для migration run и наличие restart/smoke шагов.

## Acceptance Criteria

- `scripts/deploy_server.sh` использует `compose run -T --rm mcp alembic upgrade head </dev/null`.
- `tests/test_deploy_server_script.py` проверяет migration run без stdin, restart MCP и post-deploy smoke checks.
- Targeted deploy script test и полный Docker suite проходят.
- После push прод отдаёт HTML с `#mcp-agent-instructions`.
