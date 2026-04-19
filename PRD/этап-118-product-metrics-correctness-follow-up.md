# Этап 118. Product metrics correctness follow-up

## Цель

Закрыть semantic drift в `scripts/product_metrics_report.py`, найденный повторным full-review после этапов 116-117: корректная обработка timezone-aware `--now-override` и UTC-consistent сериализация метрик по "dead accounts".

## Scope

### 118.1 Aware `--now-override`

`datetime.fromisoformat(...).replace(tzinfo=timezone.utc)` переименовывает timezone вместо конвертации. Для input вида `2026-04-18T12:00:00+03:00` это даёт ложный UTC anchor и неверные окна 24h/7d/30d.

Решение:
- нормализовать override через `_to_aware(...)` / `astimezone(timezone.utc)`;
- сохранить current behavior для naive timestamps: трактовать как UTC.

### 118.2 UTC-consistent `dead_list.last_request_at`

`_fetch_dead_account_rows()` сериализует `last_request_at` из сырого `last_used`, а не из нормализованного aware UTC значения.

Решение:
- сериализовать поле из `_to_aware(last_used)`;
- не смешивать naive и aware timestamps в одном отчёте.

### 118.3 Regression tests

Добавить тесты на:
- aware `--now-override` с `+03:00`;
- UTC suffix в `dead_list.last_request_at`.

## Non-scope

- Перепроектирование отчёта или SQL aggregation.
- Любые workflow/docs cleanup задачи из stage 119.

## Acceptance

1. `--now-override=...+03:00` корректно конвертируется в UTC before window math.
2. `dead_list.last_request_at` сериализуется в UTC-aware ISO form.
3. Existing product metrics tests остаются зелёными.

## Декомпозиция

| # | Подзадача | LOC | Файлы |
|---|---|---:|---|
| 118.1 | UTC normalization fix | ~15 | `scripts/product_metrics_report.py` |
| 118.2 | dead_list serialization fix | ~10 | `scripts/product_metrics_report.py` |
| 118.3 | Regression tests | ~30 | `tests/test_stage110_product_metrics.py` |

Total target: ~55 LOC net, без broad refactor.
