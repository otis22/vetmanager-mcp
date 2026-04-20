# Этап 121. Roadmap status sync cleanup

## Цель

Сделать `Roadmap.md` внутренне непротиворечивым: если этап уже завершён, его подпункты тоже должны быть синхронизированы со статусом `done`, чтобы файл не выглядел как частично незакрытый backlog.

## Scope

### 121.1 Stage-subtask sync

Привести к `done` внутренние подпункты в уже завершённых этапах, где фактическая работа была выполнена, но строки в Roadmap исторически остались как `todo`.

Целевые блоки:
- stages `115`, `116`, `117`;
- stages `114b`, `118`, `119`, `120`.

### 121.2 Workflow verification

После sync:
- прогнать `scripts/review_workflow_check.sh`;
- убедиться, что cleanup не создаёт новых workflow findings.

### 121.3 Audit trail

Зафиксировать cleanup в `AssumptionLog.md` как чисто документационный stage без runtime/code changes.

## Non-scope

- Любые новые продуктовые/кодовые задачи.
- Переписывание historical rationale внутри старых этапов.
- Изменение top-level статусов уже закрытых этапов.

## Acceptance

1. В `Roadmap.md` нет подпунктов `todo` внутри этапов со статусом `done`.
2. `scripts/review_workflow_check.sh` зелёный.
3. Stage 121 отражён в `AssumptionLog.md`.
