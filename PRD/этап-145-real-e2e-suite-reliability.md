# Этап 145. Real e2e suite reliability

## Контекст

После Stage 144 локальный opt-in real contour был запущен с credentials из `.env`:

`docker compose --env-file .env --profile test run --rm test python scripts/run_opt_in_real_test_suite.py`

Credentials подхватились, real API отвечал, большинство HTTP call bodies возвращали успешные `200 OK`. Suite при этом падал из-за test harness cleanup:

- старый `cleanup_orphaned_default_loop` в `tests/test_e2e_real.py` закрывал event loop до teardown async fixtures;
- общий fixture `_reset_vm_client_state` в `tests/conftest.py` очищал `_shared_http_clients` без `aclose()`, оставляя реальные sockets/transports до GC;
- opt-in real contour запускается с warning policy, которая повышает `ResourceWarning`/unraisable warnings до failures.

## Цель

Сделать real API e2e contour зелёным без ослабления warning policy и без замалчивания настоящих API failures.

## In scope

1. Убрать ручное закрытие default event loop из `tests/test_e2e_real.py`.
2. Перевести `_reset_vm_client_state` на async cleanup через существующий `reset_shared_http_client()`, чтобы реальные `httpx.AsyncClient` закрывались до сброса state.
3. Проверить:
   - targeted real subset;
   - полный opt-in real contour;
   - default skip для embedded real web-flow, который проверяет live web server lifecycle и включается отдельно через `RUN_REAL_WEB_TESTS=1`;
   - default Docker suite;
   - GitHub Actions status после push.
4. Обновить Roadmap, AssumptionLog и work log.

## Out of scope

- Менять production HTTP client pooling semantics.
- Ослаблять `build_warning_error_flags()` для real contour.
- Подгонять tests под конкретные данные dev contour, если API возвращает валидный ответ.

## Acceptance Criteria

- `docker compose --env-file .env --profile test run --rm test pytest tests/test_e2e_real.py::test_real_host_resolves tests/test_e2e_real.py::test_real_get_users -v -m real_api` passes.
- `docker compose --env-file .env --profile test run --rm test python scripts/run_opt_in_real_test_suite.py` passes or skips only tests gated by missing optional user-token/browser/web envs.
- `docker compose --profile test run --rm test` passes.
- `git diff --check` passes.
- Changes are committed, pushed, and GitHub Actions `Tests`/`Deploy Prod` are green.

## Simplicity Notes

- Use the existing `reset_shared_http_client()` API instead of duplicating client-close logic in tests.
- Keep cleanup in shared fixture so mock and real contours follow one lifecycle path.
- Keep SSL close grace opt-in via `VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS` in the real runner so default mock suite stays fast.
- Keep embedded live web-flow explicit opt-in until its uvicorn/thread lifecycle can be owned independently from the API contour.
