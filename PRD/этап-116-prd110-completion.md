# Этап 116. PRD 110 completion

## Цель

Закрыть F4 + product drift findings из super-review 2026-04-19. Scope trimmed: `--window-days` флаг УБИРАЕТСЯ (half-wired → устраняем bug, не пропагируем), PRD 110 docs drift исправлен, добавлен `expired_auto_24h` counter.

## Scope

### 116.1 Remove `--window-days` CLI flag

**Проблема:** `--window-days=N` влияет только на `requests.total_30d` row, остальные счётчики (`live_7d`, `dead_30d`, `new_*`, failures) hardcoded. Silent data mislabel.

**Решение:** убрать флаг. `window_days=30` hardcoded → `total_30d` label остаётся корректным. Пользователь, запрашивающий 7-day snapshot, в явном виде получит error "unknown arg" вместо silent wrong data.

Затронуты: `scripts/product_metrics_report.py` (argparse + `collect_metrics` signature), `.claude/commands/product-metrics.md` (whitelist args), `README.md` (skill invocation docs).

### 116.2 Add `tokens.expired_auto_24h` counter

PRD 110.1 обещает. Не реализован.

Решение: в `collect_metrics` добавить `expired_auto_24h = await _count_events(session, event_type=TOKEN_EVENT_EXPIRED, since=now - timedelta(hours=24))`; в tokens dict и markdown/json output.

### 116.3 Fix PRD 110 docs drift

- `PRD/этап-110-product-metrics.md:23,102` — `--window=30d` → убрать entirely (флаг удалён в 116.1).
- `PRD/этап-110-product-metrics.md:54` — убрать `disabled` из failures list (нет соответствующего event'а; `TOKEN_EVENT_AUTH_FAILED_DISABLED` не существует).
- `PRD/этап-110-product-metrics.md:101` — SSH example добавить `--profile production`.

### 116.4 Extend `test_record_business_event` to all 4 events

Acceptance #4 требует проверки всех 4 (account_registered / web_login_succeeded / bearer_token_issued / bearer_token_revoked). Текущий тест — 2.

### 116.5 Backfill AssumptionLog commit SHAs

- `4499` stage 110 → `778cddc`
- `4539` stage 109.10 → `3d4f75f`
- `4554` stage 109 full subset → `3234e09`

## Non-scope

- Off-by-one dead-account cutoff (`<` → `<=`) — semantics decision отдельно.
- Email masking hash-based (Codex security low) — stage 118+.
- Batched CTE queries for product_metrics_report — отдельный stage.

## Acceptance

1. `python scripts/product_metrics_report.py --window-days=7` выдаёт error "unrecognized arguments".
2. `tokens.expired_auto_24h` присутствует в output; test проверяет.
3. All 4 business events в `test_record_business_event_*`.
4. PRD 110 синхронизирован с кодом.
5. AssumptionLog commit SHAs заполнены.
6. Tests 703 → 703+ (extended test + new expired test).

## Декомпозиция

| # | LOC | Файлы |
|---|---|---|
| 116.1 | ~20 | `scripts/product_metrics_report.py`, `.claude/commands/product-metrics.md`, `README.md` |
| 116.2 | ~15 | `scripts/product_metrics_report.py`, `tests/test_stage110_product_metrics.py` |
| 116.3 | ~5 | `PRD/этап-110-product-metrics.md` |
| 116.4 | ~10 | `tests/test_stage110_product_metrics.py` |
| 116.5 | ~3 | `AssumptionLog.md` |

Total: ~55 LOC.
