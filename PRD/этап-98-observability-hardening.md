# Этап 98. Observability hardening

## Цель

Закрыть observability gaps из super-review post-stages-85-95.

## Scope

- 98.1 correlation_id в `vm_upstream_timeout/network_error/retry` warning logs
- 98.2 `circuit_open` / `circuit_half_open_busy` → `record_upstream_request` чтобы единый counter охватывал
- 98.3 `get_client_profile` обёрнут в `_instrumented_call`
- 98.4 Partial failures в `get_client_profile` → structured warning log
- 98.5 `_raise_for_status`: 4xx НЕ учитывать как `record_upstream_failure`
- 98.6 `vm_upstream_retry` log: понизить INFO → DEBUG для промежуточных attempt
- 98.7 `_instrumented_call`: добавить `operation` label для list vs by-id differentiation
