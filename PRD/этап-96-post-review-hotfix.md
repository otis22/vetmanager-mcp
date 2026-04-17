# Этап 96. Post-review hot-fix bundle

Источник: `artifacts/review/2026-04-17-post-stages-85-95.md` top-10.

## Цель

Закрыть 1 blocker + 5 urgent findings из super-review post-stages-85-95 без широкого рефактора.

## Scope

- 96.1 update_admission payload mapping (blocker)
- 96.2 get_client_profile status IN tuple (phantom enum)
- 96.3 CancelledError в partial-gather
- 96.4 Breaker HALF_OPEN 4xx probe_in_flight clear
- 96.5 filters.in_/not_in reject empty list
- 96.6 _parse_retry_after reject non-finite floats

## Acceptance

- Full suite зелёный
- lint_api_contracts exit 0 на обновлённый update_admission
- 6 новых regression тестов
