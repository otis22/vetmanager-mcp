# Этап 114. Simplicity debt + F2 inline imports

## Цель

Закрыть F2 (inline imports) из super-review 2026-04-19 Codex arbitration. Decision по 3 BC shim'ам отложен до stage 114b с explicit policy eval.

## Scope

### 114.F2 — Inline imports fix

4 inline imports без circular reason (flagged by reviewer-code + F2 arbitration):

1. `service_metrics.py:154` — `import time as _time` в `instrument_call` hot path.
2. `service_metrics.py:376` — `from request_cache import REQUEST_CACHE` в `render_prometheus_metrics`.
3. `resources/_aggregation.py:67-71` — `from exceptions import (...)` inline в `gather_sections`.
4. `resources/_aggregation.py:96` — `from exceptions import AuthError` **дубликат** line 67 import — удалить.

Circular check (manual):
- `request_cache.py` не импортирует `service_metrics.py` — OK, можно top-level.
- `exceptions.py` — pure exception classes, не импортирует `resources`.

### Вне scope (deferred)

- **Codebase-wide grep all inline imports**: существует 27 матчей в src/. Большинство — legitimate (bootstrap в `server.py`, docstring examples в `filters.py`, `tools/__init__.py` lazy register chain). Mass fix без case-by-case review поломает что-то. Deferred: отдельный аудит пайплайн.
- **BC shim policy (`tools/_aggregation.py`, `request_credentials.py`, `vetmanager_client.py` underscore re-exports)**: simplicity & architecture ревьюеры просят удалить; tests (BC invariants) просят сохранить. **Требует explicit policy decision** — не механический fix. Откладываю в stage 114b.

## Acceptance

1. `service_metrics.py` module-level импортирует `time` и `REQUEST_CACHE`.
2. `resources/_aggregation.py` имеет один `from exceptions import (...)` на module level; inline imports внутри `gather_sections` удалены.
3. Все 699 тестов зелёные, plus 1-2 новых регрессионных теста на hot-path (`instrument_call` не делает per-call import — проверяется через `sys.modules` snapshot before/after).
4. Codex review: 0 critical adequate findings.

## Декомпозиция

| # | Подзадача | LOC |
|---|---|---|
| 114.F2.a | `service_metrics.py` imports | ~5 |
| 114.F2.b | `resources/_aggregation.py` consolidate | ~20 (deletes + move) |
| 114.F2.c | Test | ~20 |

Total: ~45 LOC.

## Simplicity eval

Trigger #7 (lazy imports для не-циклического случая) явно срабатывает — это target этапа. Нет новых abstractions. Rationale: код становится проще и быстрее (hot-path without per-call dict lookup на module attribute).
