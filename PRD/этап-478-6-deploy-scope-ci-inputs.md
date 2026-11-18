# Этап 478.6 — точные CI-only входы deploy scope

## Цель

Deploy Prod `44375497970` успешно выкатил `69bfe0a`, но показал пробел:
после docs/CI merge текущий `deploy_scope_check.sh` потребовал rollout из-за
новых CI inputs и агентских документов. Устранить ложный deploy, сохранив
fail-closed поведение для неизвестных и runtime путей. Production сейчас healthy
на `69bfe0a`; этот этап не меняет runtime и не запускает deploy вручную.

## Проверенные факты

`deploy-prod.yml` проверяет полный NUL-separated diff от последнего успешного
deploy; `deploy_scope_check.sh` классифицирует по явному списку и требует deploy
для остальных путей. Все 11 путей ниже существуют в checkout и сейчас дают
`true`. Главный PRD и technical requirements не описывают CI классификатор;
контракт API Ветменеджера здесь не меняется, OpenAPI неприменим.

## Архитектурное решение

Добавить поимённо и без wildcard только:

- `scripts/ci_test_impact.py`, `scripts/test_impact_map.json`,
  `scripts/split_default_gate.py`, `scripts/run_split_default_suite.py`,
  `scripts/nightly_regression.py`, `scripts/real_group_gate.py`,
  `scripts/prepare_real_test_auth.py`;
- `.github/workflows/nightly.yml`;
- `AGENTS.md`, `AGENT_ONBOARDING.md`, `CLAUDE.md`.

Существующий поимённый `case` — граница ответственности deploy gate. Вариант
с wildcard для `scripts/` или `.github/workflows/` короче, но пропустит
runtime и сам deploy workflow; вариант с отдельным манифестом создаёт второй
источник политики для 11 строк. Выбранное дополнение сохраняет совместимость
CLI (stdin NUL paths → stdout boolean), прежнюю стоимость O(число путей) и
безопасность fail-closed. Откат — revert этих имён: лишний rollout безопаснее
пропущенного. Architecture Critique: not required — нового интерфейса, границы
ownership и runtime-поведения нет; классификатор остаётся прежним.

Проверять каждый путь отдельно и вместе с docs. Любой неизвестный путь,
runtime файл, неканонический путь, незавершённый NUL и пустой diff остаются
`true`; смешанный diff с одним из них тоже `true`. Сам изменённый
`scripts/deploy_scope_check.sh` остаётся вне allowlist, поэтому merge этого
этапа может штатно потребовать deploy. Никаких новых wildcard или правок
других селекторов. Architecture Critique не требуется: меняется только
поимённая таблица существующего deploy gate, без нового интерфейса.

## Подзадачи и приёмка

1. Test-first: точный guard на 11 путей и смешанные/unknown/runtime случаи;
   показать focused red на старом скрипте. Проверить удаление CI-only пути и
   rename runtime→CI-only как два пути `--no-renames`.
2. Расширить существующий case allowlist; каждый ранее красный node проверить
   отдельно, затем owning suite, fast, shellcheck и Bash syntax.
3. Аудит: подтвердить, что 11 путей не потребляются deploy workflow или
   runtime сборкой; полный рабочий diff review Spark → Astra + Kimi, финальные
   применимые gates, запись evidence, архивирование/structure, commit,
   committed diff review и push текущей ветки. PR/merge выполняет куратор.

Приёмка: точный docs/CI diff даёт `false`; неизвестный, runtime,
неканонический, пустой или незавершённый NUL input даёт `true`, включая
смешанный diff с одним таким путём; очередь 471+472 сохраняется.
