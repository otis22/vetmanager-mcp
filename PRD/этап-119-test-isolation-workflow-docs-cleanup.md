# Этап 119. Test isolation + workflow/docs cleanup

## Цель

Закрыть post-review хвосты, не требующие отдельной продуктовой разработки: cache-metrics test isolation, broken commit trail в `AssumptionLog.md` и release-checklist drift по `/metrics`.

## Scope

### 119.1 Cache metrics reset

`tests/conftest.py` очищает entries/tag-index, но не counters в `REQUEST_CACHE.metrics`.

Решение:
- сбрасывать `hits/misses/invalidations/evictions` вместе с cache storage;
- добавить regression test, который ловит leakage между тестами.

### 119.2 AssumptionLog SHA backfill

Этапы 116 и 117 остались с `Commit: (pending)`, хотя соответствующие коммиты уже есть в истории.

Решение:
- подставить реальные SHAs из git history;
- подтвердить, что workflow-check больше не репортит `pending_commit_sha`.

### 119.3 Release checklist sync

Checklist отстаёт от README: `/metrics` может быть gated через `METRICS_AUTH_TOKEN`.

Решение:
- обновить post-deploy пункт так, чтобы он проверял либо открытый scrape, либо auth-gated scrape по текущему env contract.

## Non-scope

- Ретро-правка старых PRD без `## Цель`.
- Борьба с `oversize_diff`/`untracked_code` до завершения всех текущих этапов.

## Acceptance

1. Cache metrics не текут между тестами.
2. `AssumptionLog.md` не содержит `(pending)` для этапов 116/117.
3. Release checklist согласован с README `/metrics` contract.

## Декомпозиция

| # | Подзадача | LOC | Файлы |
|---|---|---:|---|
| 119.1 | cache metrics reset + regression test | ~20 | `tests/conftest.py`, tests |
| 119.2 | SHA backfill | ~4 | `AssumptionLog.md` |
| 119.3 | release checklist sync | ~4 | `artifacts/release-checklist-vetmanager-mcp-ru.md` |
