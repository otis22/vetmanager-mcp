# Этап 120. Historical PRD goal-section backfill

## Цель

Убрать остаточный workflow noise от исторических PRD, в которых нет явной секции `## Цель`, хотя сами документы содержательно валидны. Этап строго документационный: структура PRD приводится к текущему contract без изменения scope, решений или статусов старых этапов.

## Scope

### 120.1 Goal-section backfill

Для каждого файла из списка workflow-check:
- добавить короткую секцию `## Цель`;
- если в PRD уже есть `## Цели`, не дублировать смысл, а добавить компактное summary и оставить подробную секцию ниже;
- если документ начинается с `## Scope` или `## Контекст`, вставить `## Цель` перед ними.

### 120.2 Workflow verification

После backfill:
- прогнать `scripts/review_workflow_check.sh`;
- убедиться, что `prd_missing_section` для целевых файлов исчез.

### 120.3 Audit trail

Обновить `AssumptionLog.md` отдельной записью с перечнем backfill-очистки и результатом workflow-check.

## Non-scope

- Переписывание содержания старых PRD.
- Пересмотр historical scope/acceptance/решений.
- Любые кодовые изменения runtime.

## Acceptance

1. Каждый PRD из списка workflow-check содержит явную секцию `## Цель`.
2. `scripts/review_workflow_check.sh` больше не выдаёт `prd_missing_section` по этим файлам.
3. Full test suite повторно зелёный перед commit.
