# Этап 127. Docs drift cleanup

## Цель

Убрать накопившийся документационный drift перед финальным release gate:
- починить битые пути к artifacts;
- синхронизировать README с фактическим числом сущностей и test command;
- обновить `artifacts/technical-requirements-vetmanager-mcp-ru.md` под текущую структуру, backup strategy и changelog;
- синхронизировать `CLAUDE.md` с реальным набором review subagents.

## Scope

1. `README.md`
   - artifact paths с суффиксом `-vetmanager-mcp-ru.md`;
   - `35` → `38` сущностей;
   - `docker compose run --rm test` → `docker compose --profile test run --rm test`.
2. `artifacts/technical-requirements-vetmanager-mcp-ru.md`
   - backup section: PostgreSQL + `scripts/backup_postgres.sh`;
   - добавить `schedule.py`, `_inactive_helpers.py`, `_slots_helpers.py` в tools/structure;
   - cache key description: включить `account_id`;
   - backfill changelog stages `117-121`.
3. `CLAUDE.md`
   - `10 subagent'ов` → `11 subagent'ов`;
   - добавить `reviewer-simplicity` в перечисление.

## Acceptance

- все 4 artifact paths в README существуют в `artifacts/`;
- README и technical requirements используют текущую test command;
- technical requirements changelog покрывает stages `97-121`;
- `CLAUDE.md` отражает фактический состав `.claude/agents/`.
