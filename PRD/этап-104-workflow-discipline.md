# Этап 104. Workflow discipline improvements

## Цель

Добавить механические workflow-gates, которые ловят пропуски stage-completion, review-resolution и artifact drift до того, как они накопятся в следующих этапах.

## Контекст

Super-review 2026-04-17 (`artifacts/review/2026-04-17-post-stages-85-95.md`) выявил 4 root-cause пропуска в workflow stages 85-95:

1. `update_admission` пропущен в stage 86 — не было sweep sibling patterns
2. `get_client_profile::status='active'` phantom enum — не было cross-check с authoritative enum
3. AssumptionLog missing для stages 92-95 — workflow-check ловил только current stage, не bulk
4. Baseline review не resolution-note'н — нет mechanism для close-out review artifacts

Цель этапа — добавить mechanical gates, которые автоматически ловят эти паттерны в будущем.

## Scope

**В scope (104 — this session):**
- 104.1 `scripts/check_stage_completion.sh` — per-stage post-commit checker
- 104.6 Pre-return checklists в 8 reviewer subagent файлах
- 104.7 Расширение `scripts/review_workflow_check.sh`: bulk AssumptionLog coverage, PRD section sanity, unresolved review verdict detection
- 104.8 `docs/stage-workflow-template.md` — step-by-step чеклист для нового этапа
- 97.7 CLAUDE.md §5a subagent count fix (8 → 10)

**Вне scope (→ 104b в отдельной сессии):**
- 104.2 Pre-commit hook для AssumptionLog — требует git hooks setup (user-env specific)
- 104.3 Field-mapping CI lint — требует canonical field dict parsing + grep infra
- 104.4 Phantom enum value lint — similar infrastructure
- 104.5 Baseline/super-review resolution tracker — Python tooling + tag parsing

## Подзадачи

### 104.1 `scripts/check_stage_completion.sh`

Per-stage checker, вызывается после commit: verifies PRD exists, AssumptionLog section exists, Roadmap status not `todo`/`in_progress`, commit message prefix `Stage N:`, test suite run hint, Codex review trace, stage diff size. Exit 1 on high-severity gaps.

### 104.6 Subagent pre-return checklists

8 reviewer files (code/architecture/docs/security/performance-and-reliability/observability/tests/product) + aggregator already has adequacy eval. Каждый получает `## Pre-return checklist` секцию с role-specific verifications.

### 104.7 `review_workflow_check.sh` extensions

- Bulk AssumptionLog coverage: iterate all `## Этап N ... done` lines in Roadmap, verify each has `## Этап N` in AssumptionLog.
- PRD section sanity: every `PRD/этап-N-*.md` должен содержать `## Цель`.
- Unresolved review verdict: detect `Do not merge` in `artifacts/review/*.md` без `Resolution` section.

### 104.8 `docs/stage-workflow-template.md`

17-step чеклист с anti-patterns и mechanical gates. Reference из CLAUDE.md §4.

### 97.7 CLAUDE.md §5a fix

Одна строка: «8 специализированных» → «8 + codex-blindspot + aggregator = 10 subagent'ов».

## Acceptance

- `scripts/check_stage_completion.sh 95` выдаёт структурированные findings (exit 1 для real gaps)
- `scripts/review_workflow_check.sh` (без args) ловит bulk missing AssumptionLog entries
- Все 8 reviewer файлов имеют `## Pre-return checklist` секцию
- `docs/stage-workflow-template.md` существует и покрывает 17 шагов
- CLAUDE.md §5a актуальный

## Вне scope deferred

104.2/3/4/5 отложены. Каждый требует отдельного focused этапа с инфраструктурой (pre-commit framework, AST-parsing для polymorphic payload detection, Python tooling для review tracker).
