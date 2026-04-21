# Этап 126. Auth-probe service hardening

## Цель

Укрепить hot-path onboarding/auth-probe в `vetmanager_connection_service.py`, чтобы:
- login/password auth не ломал валидные whitespace-sensitive пароли;
- probe/token-auth не создавали новый `httpx.AsyncClient` на каждый вызов;
- transient upstream failures ретраились детерминированно;
- probe path был покрыт метриками и structured warnings;
- concurrent save для одного account не оставлял несколько `ACTIVE` connections.

## Scope

1. `exchange_user_token`:
   - убрать `password.strip()`;
   - сохранить `login.strip()`;
   - добавить retry на `502/503/504` и `ConnectTimeout`.
2. `validate_domain_api_key_connection`, `validate_user_token_connection`, `exchange_user_token`:
   - использовать shared pool из `vm_transport.pool`;
   - использовать split timeouts из pool layer;
   - записывать upstream metrics и failure counters.
3. `save_*_connection`:
   - сериализовать save path per-account;
   - заблокировать текущие active connections внутри транзакции перед disable + insert.
4. `evaluate_connection_health`:
   - убрать silent swallow;
   - добавить `RUNTIME_LOGGER.warning(..., event_name="connection_health_failed")`.

## Декомпозиция

1. Добавить red-тесты на:
   - whitespace password passthrough;
   - shared pool usage + retry on transient 503;
   - metrics/failure counters на probe path;
   - warning log в `evaluate_connection_health`;
   - concurrent save path оставляет ровно один `ACTIVE`.
2. Вынести общий helper для upstream auth-probe calls:
   - retries;
   - metrics;
   - structured logs;
   - shared pool usage.
3. Перевести `validate_*` и `exchange_user_token` на helper.
4. Добавить per-account lock + row lock/select-for-update в save path.
5. Прогнать targeted и full test suites.

## Acceptance

- `exchange_user_token(password="  secret  ")` отправляет пароль без trim.
- `validate_domain_api_key_connection` и `validate_user_token_connection` не создают локальный `httpx.AsyncClient`.
- transient `503` probe succeeds after retries и отражается в `service_metrics`.
- `evaluate_connection_health` пишет structured warning при `VetmanagerTimeoutError`/`VetmanagerError`/`HostResolutionError`.
- concurrent save для одного account оставляет один `ACTIVE` connection.
