# Этап 438 — честные исходы opt-in real suite

## Цель

Real suite не должен выдавать зелёный результат при auth/network ошибке или пропуске запрошенного контура. `tests/test_e2e_real.py::call` сейчас превращает `AuthError` и `VetmanagerError` в `pytest.skip`; runner запускает две группы pytest и передаёт только их exit code. `.env` супервизора содержит `TEST_DOMAIN` и `TEST_API_KEY`; остальные opt-in credentials и флаги в нём отсутствуют. Ручной CI workflow передаёт API-key и опциональные user-token credentials. Требования продукта к различимым ошибкам API и сети — `artifacts/prd-vetmanager-mcp-ru.md` §4.3.1–4.3.3; стек pytest/Docker — `artifacts/technical-requirements-vetmanager-mcp-ru.md` §2.

## Инвентаризация

| Контур | Настройка на devtr6 `.env` | Действие |
| --- | --- | --- |
| `real_api`, API-key (`TEST_DOMAIN`, `TEST_API_KEY`) | Живой | Ошибки обязаны падать. |
| Direct user token (`TEST_USER_TOKEN`) | Не настроен | `skipped-not-configured` с именем контура. |
| Login/password token (`TEST_USER_TOKEN_BASE_URL`, `TEST_USER_LOGIN`, `TEST_USER_PASSWORD`) | Не настроен | `skipped-not-configured`. |
| Web account (`RUN_REAL_WEB_TESTS`) | Не настроен | `skipped-not-configured`. |
| Browser API-key (`RUN_REAL_BROWSER_TESTS`, `TEST_DOMAIN`, `TEST_API_KEY`) и browser user-token (`RUN_REAL_BROWSER_TESTS`, login/password env) | Оба не настроены | Два независимых browser-теста по маркеру `real_browser` в первой группе. Включённый flag требует API-key; login/password остаётся отдельным опциональным контуром. Compose передаёт flag из env. |
| Stage 385 multi-slot (`STAGE385_REDIS_URL` и другие отдельные сервисы) | Не настроен | `skipped-not-configured`; перечень имён в отчёте. |
| Stage 400 PostgreSQL (`STAGE400_PG_URL`) | Не настроен | `skipped-not-configured` через `skipif`; fixture-skip по отсутствию URL требует переноса в marker. |
| Прочие `real_api` smoke с локальным fixture | API-key живой, fixture может отсутствовать | Skip после запуска — `skipped-error`, suite красный; fixture нужно создать или тест сделать независимым от него. |

Переменные CI, наличие которых скрыто в secrets, нельзя считать установленными; отчёт строится по фактическому env каждого запуска. Ручной workflow передаёт login base URL по умолчанию только если обе login/password secrets существуют; иначе пустой опциональный набор не выглядит частично настроенным. `TEST_DOMAIN` может принадлежать как API-key, так и прямому user-token контуру; API key не требуется для второго. Мёртвые в текущем `.env` контуры остаются явно названными в отчёте, поскольку их запуск предусмотрен отдельным окружением. Runner проверяет ненулевое число collected tests в каждой из двух групп. Встроенный web тест во второй группе собирается даже при отсутствии `RUN_REAL_WEB_TESTS`, чтобы явно отразить неактивный контур.

## Архитектурное решение

Проблема: pytest exit 0 не различает skip по отсутствию конфигурации и skip после ошибки. Выбран локальный pytest plugin в `tests/real_suite_outcomes.py`, подключаемый только runner через `-p tests.real_suite_outcomes`, который записывает машинный итог каждого запуска в уникальный JSON; runner суммирует `passed`, `failed` (включая setup/teardown errors), `skipped-not-configured`, `skipped-error`, печатает имена ненастроенных тестов и возвращает nonzero при любом pytest exit ≠0, недостающем/невалидном JSON, нулевой сборке, `failed` или `skipped-error`. Размещение в `tests/` исключает тестовый env из production wheel/runtime-env аудита. `skipped-not-configured` назначается только если pytest применил истинный `skipif` для отсутствующих env/контура и его reason совпадает с фактическим skip; marker проверяется с фактической конфигурацией. Динамический `pytest.skip` после начала теста всегда `skipped-error`. Fixture-skip без env переносится в marker; module-level skip с `allow_module_level` в текущем real-наборе не найден. Предварительная проверка runner считает частичные настройки ошибкой (включающий флаг без credentials, только часть пары/тройки); вовсе отсутствующий опциональный набор допустим. Пара `call()` и прямые skip на `AuthError`/ошибке API удаляются; прямые skip из-за отсутствующего fixture становятся видимой ошибкой. JSON содержит только счётчики и имена тестов/контуров, без longrepr, сообщений ошибок и значений env. Вариант парсить консольный вывод отвергнут как зависимый от формата pytest; вариант запретить все skip отвергнут, потому что опциональные credentials намеренно отсутствуют. Инварианты: явно запрошенный контур при `AuthError`, `VetmanagerError`, `httpx.TransportError` или timeout даёт FAIL; ни один skip после начала теста не зелёный; mock suite не меняет выборку; секреты в отчёте не появляются. Откат: убрать plugin/runner агрегацию отдельным revert после расследования, сохранив fail-on-auth в тестах. API/MCP runtime не меняется, Architecture Critique: not required — меняется только локальная отчётность тестов.

## Подзадачи и приёмка

1. Сторож (≤150 строк): инъекция `AuthError` в настроенный `call` даёт FAIL, до исправления показать RED/SKIP; аналогично проверить network и классификацию skip.
2. Реализация (≤150 строк на подзадачу): убрать auth/network skips; перенести env fixture skip в marker; агрегировать два запуска и вывести четыре счётчика плюс имена контуров.
3. Проверка: тесты частичной конфигурации, нулевой сборки/невалидного отчёта/pytest exit, failure в каждой группе и отсутствия секретов в JSON; фокусные тесты, mock suite, real suite devtr6, аудит, strong committed diff review, полный suite по финальному SHA, push/CI. Ручной workflow уже вызывает runner. Skip без env, перечисленные в инвентаре, допустимы; fixture-dependent skip после вызова краснит suite и требует отдельного доказательства успешного теста, не замалчивается.

## Наблюдения на devtr6

До реализации `test_real_nonexistent_client_raises` скипал успешный ответ с `totalCount=0`, `client=[]`; тест теперь проверяет отсутствие записи при обоих допустимых исходах (404 или пустой список). `test_real_get_pet_profile_66` обращался к регистроневерному `/rest/api/medicalcard` и скипал 404; OpenAPI указывает `/rest/api/MedicalCards`, исправленный фокусный тест прошёл. `test_stage422_live.py::test_stage422_live_reject_and_partial_profile` после живого запроса иногда получает `existing_report_matched` вместо кандидата и скипает: это `skipped-error`, не отсутствие env. Не маскировать его как мёртвый контур и не удалять проверку, даже если полный suite поэтому станет красным.
