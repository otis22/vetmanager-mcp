# Этап 99. Reliability hardening II

## Цель

Усилить reliability в retry/breaker/shutdown путях и убрать оставшиеся lifecycle/state risks без полного redesign runtime.

## Scope

- 99.1 `_breaker_record_failure` внутри retry loop per-attempt (не только terminal)
- 99.2 HALF_OPEN probe try/finally для pre-dispatch cancellation
- 99.3 SIGTERM / FastMCP lifespan shutdown hook
- 99.4 Event-loop-scoped singleton (per-loop keying) — осторожно чтобы не сломать tests
- 99.5 Breaker thresholds tunable via env
- 99.6 DB session close ДО hash в `create_account_with_password`
