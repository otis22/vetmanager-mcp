# Этап 136. Docs hotfix after stage 135 super-review

## Контекст

Super-review `artifacts/review/2026-04-24-changed-stage-135.md` подтвердил шесть high/medium defects в docs-only cleanup stage 135. Runtime-код не затронут, но docs всё ещё могут ввести будущих агентов и операторов в заблуждение: stale full-access acceptance в историческом PRD, неверное имя Prometheus metric, смешение metrics/log events и неполная verification-команда.

## Цель

Закрыть все high/medium findings F1-F6 из stage 135 super-review без изменения runtime-кода, storage, tests или token policy.

## Scope

1. F1: `PRD/этап-28-future-scopes-rbac-bearer-tokens.md`.
   - Пометить stage 28 token issuance acceptance как историческую / superseded by stage 130+.
   - Current contract: новые токены получают scopes строго из выбранного preset; только `full_access` раскрывается во все supported scopes; legacy no-scope tokens остаются full-access compatible.
2. F2: `artifacts/operations-readiness-vetmanager-mcp-ru.md` metric names.
   - Prefix auth failure metric examples with `vetmanager_`, включая `/metrics` auth failure.
3. F3: `artifacts/operations-readiness-vetmanager-mcp-ru.md` sanitizer failure incident guidance.
   - Primary investigation path: `vetmanager_sanitizer_failures_total`, request/correlation IDs, runtime/security logs, observability runbook.
   - `token_audit_log_committed` оставить только supplemental trail when related token event exists.
4. F4: `artifacts/technical-requirements-vetmanager-mcp-ru.md` stale wording.
   - Replace stale future-only scope wording with current `token scope policy`.
5. F5: `artifacts/technical-requirements-vetmanager-mcp-ru.md` metrics/log taxonomy.
   - Keep `Observability metrics` metric-only.
   - Move `token_audit_log_committed` to a separate audit/log events subsection.
6. F6: `PRD/этап-135-technical-docs-drift-cleanup.md` verification.
   - Expand stale-wording verification to all markdown docs or explicit modified docs including README/SECURITY.
7. Record outcome in `AssumptionLog.md`, Roadmap and work log. Keep the super-review report; do not rewrite findings, but append a short follow-up block pointing to stage 136 closure artifacts.

## Не делать

- Не менять runtime `.py` files.
- Не менять token scopes/preset matrix.
- Не переписывать stage 135 report findings; allowed report change is only a follow-up/closure note after fixes.
- Не запускать новый broad super-review as part of this hotfix.

## Декомпозиция

- 136.1 PRD + review gates: <= 2 ч.
- 136.2 Apply F1-F3 docs fixes: <= 2 ч.
- 136.3 Apply F4-F6 docs fixes: <= 2 ч.
- 136.4 AssumptionLog/work log/report inclusion: <= 2 ч.
- 136.5 Checks, external diff review, commit/push: <= 2 ч.

## Верификация

- `scripts/review_workflow_check.sh 136`
- `git diff --check`
- Negative stale checks on current docs (historical review reports and
  AssumptionLog may quote original findings and are not current user/operator
  docs):
  - `printf '%s\0' README.md SECURITY.md Roadmap.md PRD/этап-28-future-scopes-rbac-bearer-tokens.md PRD/этап-135-technical-docs-drift-cleanup.md PRD/этап-136-docs-hotfix-after-stage-135-super-review.md artifacts/operations-readiness-vetmanager-mcp-ru.md artifacts/technical-requirements-vetmanager-mcp-ru.md artifacts/observability-runbook-vetmanager-mcp-ru.md | xargs -0 rg -n "Новые токены получают default[ -]full-access|future[ ]scope policy"` должен вернуть 0 хитов.
  - `printf '%s\0' README.md SECURITY.md Roadmap.md PRD/этап-28-future-scopes-rbac-bearer-tokens.md PRD/этап-135-technical-docs-drift-cleanup.md PRD/этап-136-docs-hotfix-after-stage-135-super-review.md artifacts/operations-readiness-vetmanager-mcp-ru.md artifacts/technical-requirements-vetmanager-mcp-ru.md artifacts/observability-runbook-vetmanager-mcp-ru.md | xargs -0 rg -n -P "(?<!vetmanager_)auth[_]failures_total\\b"` должен вернуть 0 хитов.
- Positive closure checks:
  - `rg -n -i "superseded by stage 130|переопределяет выпуск новых токенов" PRD/этап-28-future-scopes-rbac-bearer-tokens.md`
  - `rg -n "vetmanager_auth_failures_total\\{source=\\\"metrics" artifacts/operations-readiness-vetmanager-mcp-ru.md`
  - `rg -n "vetmanager_sanitizer_failures_total.*(основн|primary)|основн.*vetmanager_sanitizer_failures_total|primary.*vetmanager_sanitizer_failures_total" artifacts/operations-readiness-vetmanager-mcp-ru.md`
  - `rg -n "^### Audit/log events" artifacts/technical-requirements-vetmanager-mcp-ru.md`
- `awk '/^### Observability metrics/{flag=1; next} /^### /{flag=0} flag && /token_audit_log_committed/{found=1} END{exit found ? 1 : 0}' artifacts/technical-requirements-vetmanager-mcp-ru.md`
- `printf '%s\0' README.md SECURITY.md Roadmap.md PRD/этап-28-future-scopes-rbac-bearer-tokens.md PRD/этап-135-technical-docs-drift-cleanup.md PRD/этап-136-docs-hotfix-after-stage-135-super-review.md artifacts/operations-readiness-vetmanager-mcp-ru.md artifacts/technical-requirements-vetmanager-mcp-ru.md artifacts/observability-runbook-vetmanager-mcp-ru.md | xargs -0 rg -n "token_audit_log_committed"` и ручная проверка: событие находится в audit/log контексте или помечено как supplemental/дополнительный/when related; в sanitizer failure guidance `vetmanager_sanitizer_failures_total` явно назван primary/основным сигналом.
- Full suite: `docker compose --profile test run --rm test`

## Acceptance Criteria

1. F1-F6 из `artifacts/review/2026-04-24-changed-stage-135.md` закрыты.
2. No runtime code changes.
3. Operations docs use correct namespaced metric family.
4. Operations sanitizer failure guidance lists `vetmanager_sanitizer_failures_total` as primary signal; any `token_audit_log_committed` mention there is explicitly supplemental/related-token context.
5. Technical requirements separates metrics from audit/log events.
6. Stage 135 verification covers README/SECURITY or all markdown docs.
7. Super-review report has a follow-up note pointing to stage 136 closure.
8. Workflow, stale-wording checks, full suite and external diff review pass before push.
