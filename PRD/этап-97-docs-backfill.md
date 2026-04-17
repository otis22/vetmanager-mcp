# Этап 97. Docs + workflow compliance backfill

## Цель

Закрыть docs-findings super-review post-stages-85-95 — AssumptionLog propagation, canonical Roadmap статусы, tech-requirements update, README дополнения, baseline resolution (уже сделан в 104.5).

## Scope

- 97.1 AssumptionLog 92-95
- 97.2 Baseline review resolution (закрыт в 104.5, pass-through)
- 97.3 Roadmap canonical statuses: «частично done / остаток stop» → `done` + отдельные N-b `todo`/`stop` строки (оставляем форму, workflow-check regex её парсит; меняем только в критичных случаях)
- 97.4 AssumptionLog stage 7 matrix prominent obsolete header
- 97.5 tech-requirements evolution 20-89 → 20-95
- 97.6 README: VetmanagerUpstreamUnavailable, new metrics, artifact paths
- 97.7 CLAUDE.md §5a count fix — закрыт в stage 104 commit 6fdb297

## Acceptance

- `./scripts/review_workflow_check.sh` не flag'ит missing_assumption_bulk
- Current review artifacts по-прежнему clean
