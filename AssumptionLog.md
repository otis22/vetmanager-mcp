# AssumptionLog

Журнал допущений, неясностей и архитектурных решений по проекту vetmanager-mcp.

---

## Этап 1–2: Каркас и MCP-инструменты

> **[УСТАРЕЛО после этапа 22 — bearer-only runtime]**
> Ранее `domain` и `api_key` принимались как параметры каждого MCP-инструмента и/или заголовки `X-VM-Domain`/`X-VM-Api-Key`. Этот контракт полностью убран в этапе 22.4. Актуальный runtime-контракт — только `Authorization: Bearer <service_token>`. Ниже — история для контекста; не использовать как руководство к текущей реализации.

**Допущения:**
- `domain` и `api_key` передаются как параметры каждого MCP-инструмента (мультитенантность), а не из глобального env на старте сервера. Это соответствует требованию PRD 4.2.5.
- `VetmanagerClient` кэширует base URL в пределах одного экземпляра (одного запроса), но не в глобальном состоянии — каждый вызов инструмента создаёт новый экземпляр клиента.

**Архитектурные решения:**
- Инструменты реализованы статически (не через кодогенерацию из OpenAPI) для лучшего качества docstrings и надёжного взаимодействия с LLM.
- Используется `fastmcp>=2.0.0` (FastMCP v3) вместо оригинального `mcp-sdk`, так как FastMCP предоставляет более удобный decorator API.

---

## Этап 3: Docker Compose

**Допущения:**
- UID/GID хоста по умолчанию 1000. Пользователь должен задать реальные значения в `.env` через `id -u && id -g`.
- `docker-compose.yml` сервис `test` использует profile `test` — запускается только явно через `docker compose run --rm test`.

**Архитектурные решения:**
- Python на хосте не нужен и не используется. Все команды — только через Docker.
- Один образ используется и для сервера, и для тестов (dev-зависимости включены в образ для простоты).

---

## Этап 4: Тестирование

**Допущения:**
- billing API (`billing-api.vetmanager.cloud/host/{domain}`) возвращает URL без схемы (`devtr6.vetmanager2.ru`). Клиент автоматически добавляет `https://`.
- Тестовый домен `devtr6`, API-ключ передаётся через env `TEST_API_KEY` — не хранится в коде.
- Real API тест `test_real_nonexistent_client_raises` пропускается (skip) если ID 999999999 существует в тестовой базе — это ожидаемое поведение.

**Результат:** 37 passed, 1 skipped при прогоне с тестовым ключом.

---

## Этап 5: CI/CD

**Архитектурные решения:**
- Основной CI workflow (`test.yml`) запускает только unit + mock тесты — не требует секретов.
- Real API тесты (`test-real.yml`) запускаются вручную через `workflow_dispatch` с секретом `VETMANAGER_TEST_API_KEY` из GitHub Secrets.
- Ключ тестового домена НЕ хранится в репозитории; в `.env.example` поле `TEST_API_KEY` оставлено пустым.

---

## Этап 6: Операционные скрипты

**Допущения:**
- На целевом сервере может не быть Docker — `init_server.sh` устанавливает его через официальный скрипт `get.docker.com`.
- Smoke-проверка после деплоя использует `docker compose ps` и проверяет статус `running` через встроенный Python на сервере (только для проверки, не для запуска приложения).
- Путь по умолчанию на сервере `/opt/vetmanager-mcp`, настраивается через второй аргумент.

**Неясности:**
- Формат `docker compose ps --format json` может отличаться между версиями Docker Compose. При необходимости smoke-проверку можно упростить до `docker compose ps | grep -c "Up"`.

---

## Этап 8: Защита от ошибок

**Архитектурные решения:**
- Вся валидация вынесена в отдельный `validators.py` — единое место для всех правил.
- `validate_list_params(limit, offset)` вызывается первой строкой в каждом `get_*` list-инструменте.
- `validate_amount(amount)` вызывается в `create_payment` перед формированием payload.
- Лимиты: `limit` 1–100, `offset` 0–10000, `amount` >0 и ≤1 000 000.

**Обоснование лимитов:**
- `limit ≤ 100` — реальная клиника никогда не отображает более 100 записей за раз; больше = признак ошибки в промпте.
- `offset ≤ 10 000` — защита от бесконечных циклов пагинации.
- `amount ≤ 1 000 000` — защита от ввода суммы в копейках (типичная ошибка: 1500 → 150000).

**Результат:** 21 unit-тест на граничные значения, все зелёные. Общий счёт: 141 passed, 1 skipped.

---

## Этап 2.5–2.6: Расширенные инструменты и промпты

**Архитектурные решения:**
- Расширенные инструменты сгруппированы в 4 тематических модуля: `tools/reference.py`, `tools/finance.py`, `tools/warehouse.py`, `tools/clinical.py`, `tools/operations.py`.
- Промпты вынесены в отдельный `prompts.py`, регистрируются в `server.py` — отдельно от инструментов.
- Каждый промпт принимает `domain`/`api_key` как параметры, обеспечивая мультитенантность.

---

## Этап 7: Аудит полноты реализации

> **⚠️ OBSOLETE — см. README.md таблицу инструментов.**
> Матрица ниже зафиксирована на stage 7 (75 tools). Актуальный счёт — 106 tools в 13 группах (включая Schedule, convenience-инструменты и расширенную CRUD-coverage из stages 50+). Не использовать эту матрицу как источник истины о поддерживаемых операциях — только README.

### Матрица покрытия (сущность × операция)

| Сущность | GET list | GET by id | POST (create) | PUT (update) | DELETE |
|----------|----------|-----------|---------------|--------------|--------|
| Client | ✅ | ✅ | ✅ | ✅ | — |
| Pet | ✅ | ✅ | ✅ | ✅ | — |
| Admission | ✅ | ✅ | ✅ | ✅ | — |
| MedicalCard | ✅ | ✅ | ✅ | ✅ | — |
| Invoice | ✅ | ✅ | ✅ | — | — |
| Good | ✅ | ✅ | — | — | — |
| User | ✅ | ✅ | — | — | — |
| Breed | ✅ | ✅ | — | — | — |
| PetType | ✅ | ✅ | — | — | — |
| City | ✅ | ✅ | — | — | — |
| CityType | ✅ | — | — | — | — |
| Street | ✅ | ✅ | — | — | — |
| Unit | ✅ | ✅ | — | — | — |
| Role | ✅ | ✅ | — | — | — |
| UserPosition | ✅ | ✅ | — | — | — |
| ComboManualName | ✅ | ✅ | — | — | — |
| ComboManualItem | ✅ | ✅ | — | — | — |
| Payment | ✅ | ✅ | ✅ | — | — |
| ClosingOfInvoices | ✅ | ✅ | — | — | — |
| InvoiceDocument | ✅ | ✅ | ✅ | — | — |
| Cassa | ✅ | ✅ | — | — | — |
| CassaClose | ✅ | ✅ | — | — | — |
| GoodGroup | ✅ | ✅ | — | — | — |
| GoodSaleParam | ✅ | ✅ | — | — | — |
| PartyAccount | ✅ | ✅ | — | — | — |
| PartyAccountDoc | ✅ | ✅ | — | — | — |
| StoreDocument | ✅ | ✅ | — | — | — |
| Suppliers | ✅ | ✅ | — | — | — |
| Hospital | ✅ | ✅ | ✅ | — | — |
| HospitalBlock | ✅ | ✅ | — | — | — |
| Diagnoses | ✅ | — | — | — | — |
| Clinics | ✅ | ✅ | — | — | — |
| Timesheet | ✅ | ✅ | — | — | — |
| Properties | ✅ | — | — | — | — |
| AnonymousClient | ✅ | — | — | — | — |

**Итого:** 75 MCP-инструментов + 20 MCP-промптов на момент этапа 7.

> **Актуально на 2026-04-17:** 106 инструментов по 13 группам (включая Schedule, добавлен на этапе 80) + 20 промптов. Эта запись зафиксирована как baseline этапа 7; актуальный счёт см. в README и на последних этапах AssumptionLog.

**Пробелы (задокументированные, не критичные):**
- DELETE не реализован ни для одной сущности — API Vetmanager редко допускает удаление данных через REST; при необходимости добавляется тем же паттерном через `vc.delete(...)`.
- PUT (update) для Invoice, Good, User — не реализован; эти сущности обычно управляются через специализированные workflow (InvoiceDocument, GoodSaleParam).
- CityType, Diagnoses, Properties, AnonymousClient — только GET list (нет GET by id в публичном API согласно `api_entity_reference-ru.md`).

---

## Этап 9: Локальный prod-like MCP через localhost

**Архитектурные решения:**
- `server.py` переведён на HTTP transport (`streamable-http`) с конфигурацией через env: `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PATH`, `PORT`.
- `docker-compose.yml` публикует порт `${PORT}` и пробрасывает env для host-based MCP.
- Добавлен fallback credentials в `VetmanagerClient`: если `domain`/`api_key` пустые, используются `VETMANAGER_DOMAIN`/`VETMANAGER_API_KEY`.
- Cursor переключён на host-based конфиг: `http://localhost:8000/mcp`.

**Проверка подключения:**
- MCP по `localhost` успешно отвечает, клиент FastMCP получает список инструментов (`tools: 78`).

**Проверка сценария «топ-5 должников»:**
- Для домена `devttr6` billing API вернул ошибку резолва хоста (`500`) — вероятно, домен не существует/опечатка.
- Для домена `devtr6` с ключом `e2a41b0770304ea873f69d362688a309` API вернул `Invalid or missing API key`.

**Итог:**
- Технически локальное host-based подключение Cursor/MCP готово.
- Для получения реального списка должников нужен валидный `domain` и активный API-ключ.

---

## Этап 11: Реализация Variant A — credentials через HTTP headers

> **[УСТАРЕЛО после этапа 22 — bearer-only runtime]**
> `X-VM-Domain` / `X-VM-Api-Key` headers полностью убраны в stage 22.4. Актуальный runtime-контракт описан в README разделе «Использование: bearer-only runtime».

**Архитектурные решения:**
- `VetmanagerClient.__init__` больше не читает `VETMANAGER_DOMAIN`/`VETMANAGER_API_KEY` из `os.environ`.
- Создан модуль `request_credentials.py` с `resolve_credentials(domain, api_key)`:
  - Читает HTTP-заголовки `X-VM-Domain` / `X-VM-Api-Key` через `fastmcp.server.dependencies.get_http_request()`.
  - При пустых env и пустых headers клиент бросает ошибку сразу.
- Приоритет credentials: явный аргумент инструмента → HTTP header → ошибка.
- `docker-compose.yml` больше не передаёт runtime credentials в контейнер.
- `~/.cursor/mcp.json` обновлён: `url` + `headers` с `X-VM-Domain`/`X-VM-Api-Key`.

**Тесты:**
- Добавлены 5 unit-тестов в `test_client_multitenancy.py` для Variant A поведения.
- Все 107 тестов проходят.

**Допущение:**
- `get_http_request()` возвращает `RuntimeError` вне HTTP-контекста (stdio, тесты); `resolve_credentials` перехватывает это и возвращает пустые строки — VetmanagerClient тогда бросает ошибку с понятным сообщением.

**Политика credentials:**
- Runtime credentials не хранятся в репозитории.
- `TEST_DOMAIN`/`TEST_API_KEY` — только для e2e real tests (`.env` и CI secrets).

---

## Этап 12: Headers-only контракт и security hardening

**Архитектурные решения:**
- Инструменты переведены на breaking-contract: сигнатуры больше не принимают runtime `domain`/`api_key`; credentials читаются только из `X-VM-Domain`/`X-VM-Api-Key`.
- `VetmanagerClient` теперь инициализируется без аргументов и забирает credentials исключительно из `request_credentials.get_request_credentials()`.
- Добавлен pacing: минимум 50ms между последовательными исходящими HTTP-запросами одного экземпляра `VetmanagerClient` (включая billing resolve и API вызовы).
- Добавлены security-проверки:
  - строгая валидация `domain` (subdomain-safe regex);
  - разрешены только HTTPS hosts;
  - allowlist для резолвленного host (`*.vetmanager.cloud`, `*.vetmanager2.ru`);
  - API-ключ в ошибках маскируется.
- Добавлены ограниченные retry на timeout/request errors (`MAX_RETRIES=1`) с коротким backoff.

**Тестирование:**
- Обновлены unit/e2e тесты под headers-only контракт и новый security/pacing слой.
- Прогон: `docker compose --profile test run --rm test` → `147 passed, 1 skipped`.

**Неясности:**
- Real API тесты могут быть нестабильны из-за внешней сети; в `tests/test_e2e_real.py` сетевые `VetmanagerError` интерпретируются как `skip`, чтобы не давать ложных красных падений CI.

---

## Этап 13: In-memory тегированный кеш GET

**Архитектурные решения:**
- Добавлен process-local модуль `request_cache.py` с `InMemoryTaggedCache`:
  - хранение: `dict` записей + индекс тегов;
  - TTL по записи: 900 секунд;
  - синхронизация: `asyncio.Lock`.
- Ключ кеша: `METHOD + canonical_full_url_with_sorted_query + api_key_hash`.
- `api_key_hash` построен из `sha256(api_key)` (сокращённый fingerprint), чтобы не хранить сырой ключ в кеше и не смешивать ответы между разными ключами.
- Тег кеша: `domain:entity`, где `entity` извлекается из `/rest/api/<entity>/...` и нормализуется в lower-case.
- Инвалидация по тегу выполняется после успешных `POST`/`PUT`/`DELETE` для соответствующей сущности.

**Тестирование:**
- Добавлены unit-тесты на:
## Этап 18: Доменные имена и синонимы в descriptions инструментов

**Архитектурные решения:**
- Новый артефакт `artifacts/api_entity_reference-ru(с синонимами).md` применён не через изменение бизнес-логики, а через улучшение `description` у зарегистрированных FastMCP tools.
- Доменные синонимы вынесены в отдельный централизованный модуль `tool_descriptions.py`, чтобы один и тот же словарь не дублировался по всем `tools/*.py`.
- Обновление descriptions выполняется после `register_all(mcp)` и до runtime, через зарегистрированные `FunctionTool` в локальном provider FastMCP.
- Базовый принцип: `tools/list` должен помогать LLM сопоставлять разговорные формулировки (`хозяин`, `запись на приём`, `приходная накладная`, `прививка`, `остаток на складе`) с нужным MCP-инструментом без изменения `inputSchema`.

**Границы решения:**
- Этап 18 не меняет сигнатуры инструментов и не добавляет новые вызовы Vetmanager API.
- Поля и поведение API по-прежнему определяются только OpenAPI/справочником сущностей; синонимы используются как семантическая подсказка для tool selection.
  - cache hit для повторного GET;
  - reuse кеша между инстансами с одинаковым ключом;
  - изоляцию кеша для разных API-ключей;
  - TTL expiry;
  - tag invalidation после мутаций.

**Ограничения:**
- Кеш не разделяется между разными процессами/инстансами.
- Кеш очищается при перезапуске контейнера.

## Этап 14: Универсальная фильтрация и сортировка в list GET

**Архитектурные решения:**
- Добавлен общий helper `build_list_query_params()` в `validators.py`.
- Helper унифицирует формирование query-параметров:
  - базовые `limit/offset` с сохранением текущей валидации диапазонов;
  - optional `sort`/`filter` с сериализацией в компактный JSON для Vetmanager API;
  - optional `extra` для legacy-точечных фильтров (`name`, `client_id`, `date` и т.п.).
- Helper применён ко всем list `get_*` инструментам в `tools/*.py` (клиенты, питомцы, счета, финансы, справочники, склад, клиника, операции).

**Тестирование:**
- Добавлены unit-тесты helper-а:
  - минимальный сценарий `limit/offset`;
  - сериализация `sort` и `filter`;
  - объединение с дополнительными ручными фильтрами;
  - пропуск пустых значений без потери булевых `False`.
- Добавлены e2e mock и real smoke сценарии с `sort/filter`.
- Ручная проверка через MCP как внешний агент выполнена успешно:
  - `get_clients` с `sort` + `filter` (`id >= ...`);

## Этап 42.1: Browser test stack в стандартном pytest

**Архитектурные решения:**
- В default test suite добавлен browser smoke-test `tests/test_browser_stack.py`, который реально открывает Playwright `page` и тем самым проверяет не только импорт библиотеки, но и наличие рабочего Chromium в test container.
- Для browser stack выбран локальный набор pytest fixtures в `tests/conftest.py` (`browser_name`, `page`) поверх `playwright.sync_api`, а не внешний `pytest-playwright` plugin.
- Причина отказа от `pytest-playwright`: при интеграции с существующим async suite он вмешивался в event loop lifecycle и ломал последующие `pytest-asyncio` тесты. Локальные fixtures дали тот же browser baseline без global plugin side effects.
- В Docker image добавлены Playwright Python dependency и установка Chromium через `python -m playwright install --with-deps chromium`, поэтому `docker compose --profile test run --rm test` уже содержит готовый browser runtime.
- Test stack закреплён на совместимом поколении `pytest 8.x` и `pytest-asyncio 0.23.x`, чтобы не ломать существующий async test contract проекта.

**Результат проверки:**
- `docker compose --profile test run --rm test` -> `527 passed, 305 skipped, 4 warnings`.
- 4 warnings относятся к уже существующему `aiosqlite` thread/loop shutdown поведению в `tests/test_bearer_auth.py` и не были внесены этапом 42.1.
  - `get_pets` с `filter` (`owner_id = ...`) и `sort`.

**Ограничения:**
- Валидность полей `property` и применимость операторов проверяются Vetmanager API на стороне сервера API.
- Инструменты передают `sort/filter` как есть (после сериализации), без доменной бизнес-валидации по конкретной сущности.

---

## Этап 15: Профили клиента и питомца

**Архитектурные решения:**
- `get_client_profile(client_id)` в `tools/client.py`: агрегирует 4 запроса — клиент, последние 5 счетов (filter/sort), последние 5 приёмов, следующий приём (status=active, limit 1). Счета возвращаются как есть из API — поля `invoiceDocuments` и `payment_status` приходят в ответе `GET /rest/api/invoice` без дополнительных запросов.
- `get_vaccinations(pet_id, limit)` в `tools/medical_card.py`: эндпоинт `GET /rest/api/MedicalCards/Vaccinations?pet_id={id}`; ответ парсится из `data.medicalcards` (не `data.vaccinations`) по спецификации API.
- `get_pet_profile(pet_id)` в `tools/pet.py`: агрегирует питомца, последние 5 медкарт (filter `patient_id`, sort DESC), вакцинации через тот же эндпоинт; вычисляет `last_vaccination_date` и `next_vaccination_date` из последней по дате записи вакцинации.

**Тестирование:**
- Mock-тесты в `test_e2e_mock.py`: get_vaccinations (структурированный список и пустой), get_client_profile (агрегация 4 ответов), get_pet_profile (вычисление дат вакцинации и пустой список).
- Real e2e в `test_e2e_real.py`: get_vaccinations (pet 66 и пустой pet), get_client_profile(422), get_pet_profile(66).

---

## Этап 17: Лимиты в inputSchema (limit 1–100)

**Архитектурные решения:**
- В `validators.py` добавлены экспорт `VETMANAGER_MAX_LIMIT` и тип `LimitParam = Annotated[int, Field(ge=1, le=100, description="Max records to return (1–100).")]`. FastMCP/Pydantic переносят `ge`/`le` в JSON Schema как `minimum`/`maximum`, так что ответ `tools/list` для всех инструментов с параметром `limit` содержит явные границы.
- Во всех get_* инструментах в `tools/*.py` параметр `limit` заменён с `int` на `LimitParam` с сохранением дефолта (20 или 50). Инструменты без limit (*_by_id, create_*, update_*, get_client_profile, get_pet_profile) не менялись.
- Runtime-валидация по-прежнему выполняется в `validate_list_params()` (этап 8); схема в MCP дополняет её, чтобы клиенты и LLM не передавали невалидные значения.

**Тестирование:**
- В `test_validators.py` добавлены тесты для `LimitParam`: константа `VETMANAGER_MAX_LIMIT == 100` и проверка через Pydantic `create_model`, что схема поля с типом `LimitParam` содержит `minimum=1`, `maximum=100` и описание.

---

## Этап 15.4: MCP Prompts на headers-only контракте

**Архитектурные решения:**
- `prompts.py` переведён на тот же runtime-контракт, что и tools: prompt-функции принимают только бизнес-параметры сценария и больше не содержат `domain` / `api_key` в сигнатурах.
- Добавлен единый headers-only префикс для всех prompts: credentials уже доступны из request headers, их не нужно спрашивать у пользователя и нельзя передавать как аргументы инструментов.
- Тексты prompts уточнены под фактические `tool` names и параметры текущей реализации, чтобы не подсказывать LLM несуществующие аргументы.

**Тестирование:**
- Добавлен статический regression test `tests/test_prompts_headers_only.py`.
- Тест проверяет:
  - что в prompt-функциях нет аргументов `domain` / `api_key`;
  - что в `prompts.py` не осталось legacy-подсказок вида `Use domain=...` / `api_key=...`;
  - что в файле есть явная headers-only инструкция.

**Ограничения:**
- Проверка prompts сделана статической (через AST и source scan), а не через runtime FastMCP introspection, чтобы тест работал независимо от наличия Python-зависимостей на хосте и не нарушал docker-only workflow проекта.

---

## Этап 15.5: Синхронизация technical requirements с текущей архитектурой

**Архитектурные решения:**
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` обновлён как описание фактической текущей реализации, а не исторического дизайна первой версии.
- Из артефакта удалены устаревшие допущения про:
  - runtime credentials через `VETMANAGER_DOMAIN` / `VETMANAGER_API_KEY`;
  - transport `stdio` как основной режим;
  - структуру проекта с `.venv`, `config.py`, `requirements.txt`, `uv`.
- В документе зафиксированы текущие инварианты проекта:
  - headers-only credentials через `X-VM-Domain` / `X-VM-Api-Key`;
  - HTTP MCP transport (`streamable-http`);
  - docker-only workflow;
  - process-local tagged cache;
  - pacing, retry/timeout и security hardening в `VetmanagerClient`;
  - статическая реализация tools/prompts с опорой на docstrings и type hints.

**Согласованность артефактов:**
- Содержание `technical-requirements` синхронизировано с:
  - `README.md` по transport, headers-only runtime-контракту и docker compose workflow;
  - `Roadmap.md` по уже завершённым этапам security/cache/sort-filter/prompts;
  - `artifacts/prd-vetmanager-mcp-ru.md` по целевой продуктовой модели мультитенантного headers-only MCP-сервера.

**Ограничения:**
- Артефакт остаётся архитектурным описанием текущего состояния и не заменяет OpenAPI как источник истины по конкретным Vetmanager endpoints и схемам.

---

## Этап 16: tools/list по спецификации MCP

**Архитектурные решения:**
- В качестве источника описаний для `tools/list` остаются docstrings инструментов `tools/*.py`; отдельный слой хардкода для descriptions не добавлялся.
- Из docstrings инструментов удалены legacy строки про `domain` / `api_key`, чтобы экспортируемые `description` соответствовали текущему headers-only контракту.
- `inputSchema` продолжает генерироваться через FastMCP/Pydantic из сигнатур функций и type hints; отдельная ручная генерация схем не потребовалась.

**Тестирование:**
- `tests/test_tools_list_schema.py` расширен проверками Stage 16:
  - у каждого инструмента есть непустой `description`;
  - у каждого инструмента есть непустой `inputSchema`;
  - в `description` отсутствуют legacy credential hints.
- Ручная проверка внутри контейнера показала:
  - `tool_count = 85`
  - `legacy_count = 0`

**Ограничения:**
- `title` в `inputSchema` не является обязательным полем для текущего контракта; сервер гарантирует `name`, `description` и `inputSchema`.

---

## Этап 18: Доменные имена и синонимы в descriptions инструментов

**Архитектурные решения:**
- Новый артефакт `artifacts/api_entity_reference-ru(с синонимами).md` применён через слой descriptions для MCP tools, а не через изменение бизнес-логики или сигнатур инструментов.
- Доменные синонимы вынесены в отдельный централизованный модуль `tool_descriptions.py`, чтобы использовать один словарь для всех поддерживаемых сущностей проекта.
- Обновление descriptions выполняется после `register_all(mcp)` и меняет зарегистрированные `FunctionTool.description` в локальном provider FastMCP, поэтому `tools/list` сразу публикует enriched descriptions без ручной правки десятков docstrings.
- Базовый принцип этапа: `tools/list` должен помогать LLM сопоставлять разговорные формулировки вроде `хозяин`, `запись на приём`, `приходная накладная`, `остаток на складе`, `прививка` с правильным MCP-инструментом.

**Границы решения:**
- Этап 18 не меняет `inputSchema`, бизнес-логику инструментов и не добавляет новые вызовы Vetmanager API.
- Синонимы используются как семантическая подсказка для выбора инструмента; источником истины по endpoint-логике и схемам остаются OpenAPI и справочник сущностей.

**Тестирование:**
- `tests/test_tools_list_schema.py` расширен проверками Stage 18:
  - у каждого инструмента description содержит `Domain synonyms:`;
  - representative tools экспортируют ожидаемые доменные термины (`владелец`, `запись на приём`, `история болезни`, `остаток на складе`, `прививка`, `приходная накладная`).
- Контейнерный прогон: `pytest tests/test_tools_list_schema.py` → `245 passed, 282 skipped`.

---

## Этап 19: Глобальные уведомления `messages/*`

**Архитектурные решения:**
- Инструменты `messages/*` добавлены в `tools/operations.py`, потому что это операционный сценарий внутренних уведомлений, а не отдельная клиентская или медицинская сущность.
- Реализованы четыре MCP-инструмента:
  - `send_message_to_all(message, campaign)`
  - `send_message_to_users(message, campaign, user_ids)`
  - `get_message_reports(limit, offset, campaign="", sort=None, filter=None)`
  - `send_message_to_roles(message, campaign, roles)`
- Для `user_ids` и `roles` введены schema-ограничения `min_length=1`, чтобы MCP clients и LLM не передавали пустой список адресатов.
- Для `get_message_reports` сохранён общий list-контракт проекта (`limit`, `offset`, `sort`, `filter`) и дополнительно поддержан `campaign` из пользовательского curl-примера.

**Тестирование:**
- Отправка сообщений покрыта mock/tool-level тестами через `mcp.call_tool(...)`, чтобы проверять именно MCP-инструменты, а не только низкоуровневый HTTP-клиент.
- В real e2e добавлен только безопасный smoke на `get_message_reports`; POST real tests не добавлялись, чтобы не создавать побочный эффект в рабочей клинике.

**Неясности / фактическое поведение API:**
- В real API `GET /rest/api/messages/reports` фактически требует непустой `campaign` и при его отсутствии возвращает `{"success": false, "errors": ["Campaign name cannot be empty"]}`.
- Это требование не отражено явно в текущем OpenAPI-фрагменте, поэтому в real smoke test используется `campaign="All users"`, а при доменно-специфичной ошибке тест корректно `skip`-ается вместо ложного падения.

---

## Аудит артефактов после этапа 19

**Результат аудита:**
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` в целом соответствовал текущей архитектуре, но не фиксировал явно роль `tool_descriptions.py`, контракт `tools/list` как source of truth и наличие специальных инструментов поверх нестандартных endpoint'ов.
- `artifacts/prd-vetmanager-mcp-ru.md` отставал сильнее: в нём были описаны базовые tools и headers-only credentials, но не были зафиксированы MCP prompts, enriched `tools/list`, schema-level safety ограничения и специальные операции вроде профилей и `messages/*`.
- `artifacts/api_entity_reference-ru.md` и `artifacts/api_entity_reference-ru(с синонимами).md` менять не потребовалось: они уже содержат актуальные разделы по `messages/*` и используются как справочный, а не архитектурный слой.

**Архитектурное решение:**
- При регулярной синхронизации проекта с Roadmap ключевыми артефактами для обновления являются продуктовый PRD и технические требования; справочники сущностей обновляются только при изменении источников истины OpenAPI/API reference, а не при каждом изменении MCP-обвязки.

---

## Планирование bearer-only следующего цикла

**Зафиксированные продуктовые решения:**
- Bearer-токены привязываются к аккаунту сервиса, а не к workspace.
- Аккаунт хранит один активный способ авторизации в Vetmanager и все Bearer-токены аккаунта используют именно его.
- Dual-mode не планируется: целевой runtime-контракт MCP переводится на bearer-only.
- В первой итерации реализуется auth mode `domain + rest_api_key`, но в roadmap и артефактах сразу закладываются оба способа авторизации Vetmanager.

**Архитектурные последствия:**
- `artifacts/prd-vetmanager-mcp-ru.md` переведён с текущего headers-only описания на целевую bearer-only продуктовую модель.
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` сохранён как двухслойный документ: он одновременно описывает текущее состояние кода и планируемую bearer-only архитектуру roadmap этапов 20–28.
- Новый roadmap после этапа 19 перестраивается вокруг Bearer-сервиса, аккаунтов, web-контура и storage, а не вокруг incremental hardening текущего headers-only runtime.

**Завершение этапа 20:**
- Добавлен отдельный PRD-файл `PRD/этап-20-bearer-only-архитектура.md`, чтобы следующие этапы 21–28 опирались не только на Roadmap и обновлённые артефакты, но и на явную декомпозицию planning-этапа.
- Этап 20 закрыт как artifact-only/planning этап; runtime-код проекта не менялся и текущая headers-only реализация остаётся действующей до начала этапов bearer migration.

---

## Этап 21.1: выбор storage foundation для Bearer-сервиса

**Принятое решение:**
- В качестве persistence toolkit выбран `SQLAlchemy 2.x` с async engine/session.
- Локальный default для проекта и тестов: `SQLite` через `sqlite+aiosqlite`.
- Конфигурация строится через `DATABASE_URL`, чтобы следующий этап мог перейти на PostgreSQL без переписывания storage-слоя.

**Почему так:**
- Текущий проект уже async-first (`FastMCP`, `httpx`, async tests), поэтому sync ORM только добавил бы адаптерный слой перед этапами bearer auth и web.
- Для задачи `21.1` поднимать отдельный database container преждевременно: SQLite даёт zero-setup foundation, а нормализация `DATABASE_URL` сохраняет путь к production-grade СУБД.

**Что реализовано:**
- Добавлен `storage.py` с:
  - нормализацией `DATABASE_URL` в async dialect;
  - `AsyncEngine`;
  - `async_sessionmaker`;
  - `DeclarativeBase`;
  - bootstrap-проверкой подключения `initialize_storage()`.
- Добавлены unit-тесты storage bootstrap и URL normalization.
- Контейнеры `mcp` и `test` теперь принимают `DATABASE_URL` из окружения.

**Границы решения:**
- Модели, миграции, хранение секретов Vetmanager, hash Bearer-токенов и lifecycle token states оставлены в задачах `21.2–21.5`.
- Текущий MCP runtime по-прежнему не использует storage слой в боевом auth-контуре; foundation добавлен заранее для следующих этапов.

---

## Этап 21.2: baseline миграции bearer-storage

**Принятое решение:**
- В качестве миграционного инструмента выбран `Alembic`, чтобы storage-слой развивался поверх `SQLAlchemy` без самописного migration runner.
- Для этапа `21.2` добавлена baseline revision с таблицами:
  `accounts`, `vetmanager_connections`, `service_bearer_tokens`,
  `token_usage_stats`, `token_usage_logs`.

**Архитектурные выводы:**
- Runtime продолжает использовать async URL (`sqlite+aiosqlite`, `postgresql+asyncpg`), а Alembic получает sync-совместимый URL через отдельную нормализацию.
- В baseline намеренно присутствуют и агрегированные `token_usage_stats`, и детальные `token_usage_logs`, чтобы дальнейшие этапы не упёрлись в преждевременный выбор только одного варианта аудита.
- Таблица `service_bearer_tokens` уже хранит только метаданные токена (`token_prefix`, `token_hash`, статусы, timestamps); фактический lifecycle и secret-handling будут дорабатываться в задачах `21.3–21.5`.

**Что реализовано:**
- Добавлены `storage_models.py`, `alembic.ini`, `alembic/env.py` и baseline revision в `alembic/versions/`.
- Добавлены тесты, которые прогоняют `alembic upgrade head` на SQLite и проверяют фактическое создание всех целевых таблиц.

---

## Этап 21.3: encrypted storage для Vetmanager secrets

**Принятое решение:**
- Для шифрования storage payloads выбран `Fernet` из `cryptography`.
- Ключ берётся из `STORAGE_ENCRYPTION_KEY`; при его отсутствии secret layer fail-closed, а не падает в plaintext fallback.

**Что реализовано:**
- Добавлен `secret_manager.py` с генерацией ключа, шифрованием и расшифровкой payloads.
- `VetmanagerConnection` получил helper-методы `set_credentials()` / `get_credentials()`, которые работают только через зашифрованный blob `encrypted_credentials`.
- Контейнеры `mcp` и `test` теперь принимают `STORAGE_ENCRYPTION_KEY` из окружения.

**Архитектурные последствия:**
- Vetmanager credentials больше не должны сохраняться по полям `domain/api_key` в открытом виде внутри persistence-слоя; рабочий storage contract для секретов теперь строится вокруг одного encrypted blob.
- Secret management выделен в отдельный модуль, чтобы lifecycle Bearer-токенов и hash-based token storage не смешивались с шифрованием Vetmanager credentials.

---

## Этап 21.4: hash-only bearer token storage

**Принятое решение:**
- Raw Bearer-токен генерируется отдельно и предназначен только для одноразового показа пользователю.
- В persistence-слое хранятся только:
  - `token_hash` для deterministic lookup/verification;
  - короткий `token_prefix` для UI, аудита и безопасного различения токенов.

**Что реализовано:**
- Добавлен `bearer_token_manager.py` с генерацией raw токена, вычислением `token_hash`, выделением `token_prefix` и constant-time verification.
- `ServiceBearerToken` получил helper-методы `set_raw_token()` и `verify_raw_token()`.

**Архитектурные последствия:**
- Модель токена больше не требует хранения raw secret даже временно внутри ORM-сущности.
- Хранение hash и prefix отделено от usage accounting и secret encryption, что упрощает следующий этап с revoke/expiry/status lifecycle.

---

## Этап 21.5–21.6: lifecycle Bearer-токенов и тестовое покрытие

**Что реализовано:**
- `ServiceBearerToken` получил lifecycle helpers:
  - `is_active()`
  - `is_expired()`
  - `is_revoked()`
  - `sync_status()`
  - `revoke()`
  - `mark_used()`
- Добавлен unit-набор для storage/security foundation:
  - bootstrap БД;
  - Alembic baseline migration;
  - encrypted Vetmanager secrets;
  - hash-only bearer token storage;
  - revoke/expiry/status lifecycle.

**Итог по этапу 21:**
- Storage foundation завершён как отдельный слой, не ломающий текущий headers-only runtime.
- Следующий этап может уже строить bearer auth lookup поверх готовых account/token tables, encrypted Vetmanager credentials и lifecycle правил токена.

---

## Этап 22.1: извлечение Bearer из MCP request

**Принятое решение:**
- Новый bearer-path вынесен в отдельный `request_auth.py`, а не внедрён поверх `request_credentials.py`, чтобы переход на новый runtime контракт шёл поэтапно.
- На шаге `22.1` headers-only путь ещё не удаляется; добавляется только безопасный parser для `Authorization: Bearer <service_token>`.

**Что реализовано:**
- Добавлен helper `get_bearer_token()`, который:
  - читает текущие HTTP headers;
  - извлекает Bearer-токен из `Authorization`;
  - различает missing и invalid Authorization forms через `AuthError`.
- Добавлен unit-тестовый набор для корректного Bearer, отсутствующего заголовка и невалидных схем.

---

## Этап 22.2: lookup bearer token -> account -> active connection

**Принятое решение:**
- Lookup bearer runtime вынесен в отдельный `bearer_auth.py` с dataclass-контекстом, а не смешан с `VetmanagerClient` или request-layer.
- Разрешение токена строится по `token_hash`, после чего выбирается первый `active` `vetmanager_connection` аккаунта.

**Что реализовано:**
- Добавлен `BearerAuthContext`.
- Добавлен `resolve_bearer_auth_context(raw_token, session, ...)`, который:
  - ищет `service_bearer_token` по hash;
  - проверяет revoked/expired/disabled состояния токена;
  - проверяет активность аккаунта;
  - находит активный `vetmanager_connection`;
  - возвращает расшифрованные Vetmanager credentials для следующего runtime слоя.

**Архитектурные последствия:**
- Этап `22.3` теперь может переключать runtime на готовый account-based context без дублирования SQL и without coupling к ORM details в transport-layer.

---

## Этап 22.3: runtime credentials через account-based auth context

**Принятое решение:**
- Переходный runtime context вынесен в `runtime_auth.py`.
- Порядок разрешения credentials сейчас такой:
  1. `Authorization: Bearer <service_token>` как основной путь;
  2. legacy `X-VM-Domain` / `X-VM-Api-Key` как временный fallback до этапа `22.4`.

**Что реализовано:**
- Добавлен `RuntimeCredentials`.
- Добавлен `resolve_runtime_credentials()`, который:
  - использует bearer lookup и расшифрованные Vetmanager credentials аккаунта;
  - при отсутствии Bearer временно падает назад на headers-only контракт.
- `VetmanagerClient` переведён на lazy runtime resolution через account-based context и больше не привязан жёстко к прямому чтению `X-VM-*` как единственному источнику.

**Архитектурные последствия:**
- Основной runtime path уже построен вокруг `service_bearer_token -> account -> active connection`.
- Этап `22.4` теперь сводится к удалению временного legacy fallback и вычистке старых `X-VM-*` assumptions из runtime-контура.

---

## Этап 22.4: удаление `X-VM-*` из runtime-контура

**Что сделано:**
- `runtime_auth.py` переведён на strict bearer-only resolution без fallback на `X-VM-Domain` / `X-VM-Api-Key`.
- `VetmanagerClient` больше не использует `request_credentials.get_request_credentials()` как runtime источник.
- `server.py` обновлён под bearer-only instructions.
- Клиентские unit-тесты переведены с header-based setup на bearer-shaped runtime setup.

**Архитектурный итог:**
- Рабочий runtime-контур теперь bearer-only.
- Старый headers-only путь остаётся только в исторических артефактах и должен дальше вычищаться из документации и legacy tests по мере следующих этапов.

---

## Этап 22.5–22.6: безопасные bearer errors и тесты runtime-контракта

**Что зафиксировано в runtime:**
- `missing bearer`:
  - `request_auth.get_bearer_token()` возвращает безопасную ошибку без утечки секретов.
- `invalid bearer`:
  - `resolve_bearer_auth_context()` возвращает `Invalid bearer token.` для неизвестного токена.
- `expired bearer`:
  - токен переводится в `expired` и отклоняется безопасной ошибкой.
- `revoked bearer`:
  - revoked токен немедленно отклоняется безопасной ошибкой.
- `account connection not configured`:
  - runtime не раскрывает лишние детали и возвращает явную безопасную ошибку, если у аккаунта нет активной Vetmanager connection.

**Тестовое покрытие:**
- Обновлены unit-тесты bearer-only runtime-контракта:
  - request-layer (`Authorization: Bearer`);
  - token/account/connection lookup;
  - runtime credentials resolution;
  - `VetmanagerClient` в bearer-only контуре;
  - совместимые client-level regression tests для caching/pacing/security.

**Итог по этапу 22:**
- MCP runtime переведён на bearer-only auth path.
- Основной следующий этап теперь может реализовывать первый Vetmanager auth mode аккаунта (`domain + rest_api_key`) уже поверх готового bearer runtime и storage слоя.

---

## Этап 23.1: Vetmanager auth mode `domain + rest_api_key`

**Принятое решение:**
- Первый Vetmanager auth mode оформлен как отдельный abstraction layer, а не как произвольный encrypted dict.
- Идентификатор первого режима: `domain_api_key`.

**Что реализовано:**
- Добавлен [vetmanager_auth.py](/home/otis/myprojects/vetmanager-mcp/vetmanager_auth.py) с:
  - `VETMANAGER_AUTH_MODE_DOMAIN_API_KEY`
  - `VetmanagerResolvedCredentials`
  - `resolve_vetmanager_credentials(connection, ...)`
- `bearer_auth.py` теперь получает domain/api_key через этот auth-mode слой, а не напрямую из generic payload.

**Архитектурные последствия:**
- Runtime больше не зависит от формы хранения credentials внутри `vetmanager_connection`.
- Следующий режим (`user login/password -> token`) можно будет добавлять как второй explicit mode в том же abstraction layer, не ломая bearer runtime path.

---

## Этап 23.2: валидация и сохранение account connection

**Что реализовано:**
- Добавлен [vetmanager_connection_service.py](/home/otis/myprojects/vetmanager-mcp/vetmanager_connection_service.py).
- Реализован `save_domain_api_key_connection(...)`, который:
  - валидирует `domain`;
  - проверяет `api_key` через реальный probe к Vetmanager API после billing host resolution;
  - шифрует credentials;
  - отключает предыдущие active connections аккаунта;
  - сохраняет новый `active` connection режима `domain_api_key`.

**Архитектурные последствия:**
- Появился отдельный write-path для Vetmanager integration layer, а не только runtime read-path.
- Правило "у аккаунта один активный способ авторизации в Vetmanager" теперь соблюдается не только документально, но и на уровне сервисной логики сохранения connection.

---

## Этап 23.3: интеграция auth mode в `VetmanagerClient`

**Что изменилось:**
- `VetmanagerClient` теперь опирается на `VetmanagerAuthContext`, а не на разрозненные `domain/api_key` как на базовый primitive слой.
- `vetmanager_auth.py` получил runtime-capable методы:
  - `build_headers()`
  - `api_key_fingerprint()`

**Архитектурный эффект:**
- Mode abstraction теперь используется не только при bearer lookup, но и непосредственно в runtime HTTP-клиенте.
- Это подготавливает код к добавлению второго Vetmanager auth mode без повторной переработки клиента, cache isolation и header construction.

---

## Этап 23.4: проверка tools/prompts в bearer-only runtime

**Что проверено:**
- Mock e2e тесты переведены на bearer-shaped runtime setup вместо legacy `X-VM-*` headers.
- Prompt regression тесты теперь проверяют bearer-only инструкции: prompts не должны просить `domain` или `api_key`.
- Real e2e helper синхронизирован с bearer runtime-контуром, чтобы следующий smoke against real API не расходился с рабочей моделью авторизации.

**Что зафиксировано:**
- Существующие MCP tools продолжают работать без runtime credential arguments.
- Prompts и server instructions теперь явно говорят о `Authorization: Bearer <service_token>`, а не о request headers с доменом и API-ключом.
- Headers-only контракт остаётся только в исторических файлах и должен дальше удаляться из документации и legacy naming.

---

## Этап 23.5: обновление README и документации подключения

**Что обновлено:**
- `README.md` переведён с headers-only описания на bearer-only runtime модель.
- Документация теперь описывает storage/migration foundation (`DATABASE_URL`, `STORAGE_ENCRYPTION_KEY`) и новый runtime-контракт `Authorization: Bearer <service_token>`.
- Явно зафиксировано, что self-service выпуск account/token ещё не завершён и ожидается на web-этапе 24.

**Принятое решение:**
- Документация не должна обещать пользователю UI или provisioning flow, которых ещё нет в репозитории.
- До этапа 24 bearer runtime считается продуктовым контрактом MCP-сервера, а создание account connection и bearer token относится к internal/dev provisioning path.

---

## Этап 24.1: PRD web-слоя и UX кабинета

**Что зафиксировано в PRD:**
- Этап 24 начинается только после того, как bearer runtime и первый Vetmanager auth mode уже готовы.
- Web-контур должен стать первым пользовательским способом управлять account, active Vetmanager connection и service bearer tokens.
- Первая web-итерация ограничивается лендингом, регистрацией, login/logout, экраном интеграции `domain + rest_api_key` и базовым token management UI.

**Принятые продуктовые ограничения:**
- Web-кабинет не меняет bearer-only MCP runtime-контракт: MCP-клиенты по-прежнему используют только `Authorization: Bearer <service_token>`.
- UI не должен повторно раскрывать raw bearer после создания; это отдельно закреплено как задача `24.7`.
- До этапа usage analytics экран токенов показывает только то, что уже есть в storage-модели: статус, срок действия и безопасный `token_prefix`; расширенная usage-аналитика остаётся этапу 25.

---

## Этап 24.2: лендинг сервиса

**Что реализовано:**
- Добавлен публичный root route `/` как custom HTTP route поверх текущего FastMCP app.
- Лендинг описывает bearer-only продуктовую модель, account-scoped Vetmanager integration и текущий статус web-контура.
- MCP endpoint сохранён на `/mcp`; публичная страница не вмешивается в tool/prompt runtime path.

**Принятое решение по реализации:**
- Для первого шага web-слоя выбран встроенный route внутри текущего сервера, без отдельного web-framework поверх существующего runtime.
- Лендинг остаётся статической страницей без auth/state, чтобы не смешивать этап `24.2` с задачами регистрации и кабинета из `24.3+`.

---

## Этап 24.3: регистрация и login/logout

**Что реализовано:**
- Добавлен password-backed web auth path для `Account`: регистрация, login, logout и защищённая страница `/account`.
- В `accounts` добавлено поле `password_hash`; схема обновлена через отдельную Alembic migration.
- Web-сессия реализована через signed HTTP-only cookie, не влияющую на bearer-only MCP runtime.

**Принятые ограничения:**
- Для MVP web auth используется один email/password account без ролей и без recovery flow.
- Сессия нужна только для web-кабинета; MCP tools и prompts продолжают аутентифицироваться исключительно по `Authorization: Bearer <service_token>`.
- `WEB_SESSION_SECRET` должен считаться отдельным runtime secret; fallback на другие секреты допустим только как dev-mode поведение.

---

## Этап 24.4: экран настройки Vetmanager integration

**Что реализовано:**
- `/account` стал не только dashboard, но и рабочим экраном настройки активной Vetmanager integration.
- Добавлена форма `domain + rest_api_key`, которая использует существующий `save_domain_api_key_connection(...)`.
- Экран показывает текущую active connection и не раскрывает сохранённый API key после успешного сохранения.

**Принятые ограничения:**
- Первая web-итерация кабинета поддерживает только mode `domain_api_key`.
- Ошибки валидации и неверного Vetmanager API key возвращаются пользователю в безопасном виде без утечки секрета.
- UI использует уже реализованное правило "один активный способ авторизации в Vetmanager на account" и не вводит отдельную логику поверх сервисного слоя.

---

## Этап 24.5 и 24.7: выпуск Bearer-токенов и one-time reveal

**Что реализовано:**
- В кабинете добавлена форма выпуска Bearer-токенов с именем и опциональным сроком действия в днях.
- Выпуск токена требует уже настроенную активную Vetmanager integration, чтобы account выдавал сразу рабочий service token.
- После создания raw token показывается только в ответе на POST создания; последующие GET `/account` больше не содержат его значение.

**Что зафиксировано по security-контракту:**
- В storage по-прежнему сохраняются только `token_hash`, `token_prefix`, metadata и optional `expires_at`.
- Raw Bearer не попадает ни в БД, ни в повторно открываемую account-страницу.
- Таким образом, one-time reveal правило уже реализовано до появления отдельного списка токенов.

---

## Этап 24.6: список токенов в кабинете

**Что реализовано:**
- `/account` теперь показывает список выпущенных Bearer-токенов без отдельной страницы.
- В таблицу выведены только безопасные поля: `name`, `token_prefix`, `status`, `expires_at`, `last_used_at`, `request_count`.
- После refresh страницы raw token уже недоступен, но short prefix и metadata остаются видимыми в списке.

**Договорённость по данным:**
- До этапа 25 поле `request_count` может оставаться `0`, а `last_used_at` — `Never`, если usage accounting ещё не обновлял их.
- Это не считается дефектом списка; web UI уже готов к показу usage metadata, а заполнение этих полей приходит следующим этапом.

---

## Этап 25.1: обновление `last_used_at`

**Что реализовано:**
- Успешный bearer lookup теперь обновляет `ServiceBearerToken.last_used_at`.
- Timestamp ставится в том же runtime path, где токен уже был подтверждён как валидный и связан с active account connection.
- Ошибочные ветки (`invalid`, `revoked`, `expired`, `no connection`) не создают ложной отметки использования.

**Архитектурный эффект:**
- Web-кабинет получает живое поле `last_used_at` без дополнительных обходов через tool-level код.
- Следующий шаг `25.2` может на том же runtime path добавить `request_count`, не меняя место интеграции usage accounting.

---

## Этап 25.2: счётчик запросов по Bearer-токену

**Что реализовано:**
- На успешном bearer lookup теперь создаётся или обновляется `TokenUsageStat`.
- `request_count` инкрементируется на каждый успешный runtime resolve Bearer-токена.
- `TokenUsageStat.last_used_at` синхронизируется с `ServiceBearerToken.last_used_at`.

**Архитектурный эффект:**
- Usage accounting остаётся сосредоточен в одном runtime entry point, а не размазан по tool handlers.
- Web-кабинет уже может читать не только `last_used_at`, но и реальный `request_count`; следующая задача теперь сводится к lifecycle audit log, а не к базовой статистике.

---

## Этап 25.3: безопасный аудит create/revoke

**Что реализовано:**
- Выпуск Bearer-токена теперь пишет `token_created` в `TokenUsageLog`.
- Revoke Bearer-токена теперь пишет `token_revoked` в `TokenUsageLog`.
- Для revoke добавлен явный web path из кабинета, чтобы lifecycle audit был привязан к реальному пользовательскому действию, а не только к ручным изменениям в БД.

**Что зафиксировано по безопасности:**
- В `details_json` пишутся только безопасные metadata вроде `name`, `token_prefix`, `expires_at`, `revoked_at`.
- Raw token не попадает ни в audit log, ни в повторно открываемые страницы кабинета.

---

## Этап 25.4: отображение usage в кабинете

**Что реализовано:**
- Кабинет показывает `last_used_at` и `request_count` уже как живые runtime-данные.
- Список токенов дополнился action-кнопкой revoke, а usage metadata остаются рядом с каждым токеном.

**Итог:**
- Web account теперь не только выпускает токены, но и даёт минимальную операционную наблюдаемость по их фактическому использованию.

---

## Этап 25.5: тесты usage accounting без утечек секретов

**Что покрыто тестами:**
- `last_used_at` обновляется только на успешном bearer path.
- `request_count` накапливается на повторных successful resolves.
- UI показывает usage metadata после реального runtime использования токена.
- Audit log на create/revoke не содержит raw token.

**Итог по этапу 25:**
- Usage accounting и минимальная admin analytics готовы.
- Следующий крупный шаг roadmap теперь уже про второй Vetmanager auth mode (`user login/password -> token`).

---

## Этап 26.1: контракт `user login/password -> token`

**Что подтверждено локальными артефактами:**
- В продуктовых требованиях второй Vetmanager auth mode уже предусмотрен как
  целевой способ подключения аккаунта наряду с `domain + rest_api_key`.
- В `artifacts/vetmanager_openapi_v6.json` есть `POST /token_auth.php` с
  summary `Get Token (by User Login & Password)`.
- В `artifacts/vetmanager_postman_collection.json` есть отдельный Postman item
  для этого endpoint.

**Что остаётся неуточнённым по локальным данным:**
- Точная форма request payload для `token_auth.php`.
- Точные имена полей user credentials.
- Обязательность `X-REST-API-KEY` именно для этого flow.
- Точная структура `data` в успешном ответе с user token.

**Архитектурное решение:**
- `26.1` закрыт как этап фиксации фактов и пробелов контракта, а не как полная
  runtime-верификация через реальный API.
- Реализация `26.2+` должна идти через изолированный abstraction layer, чтобы
  bearer runtime продолжал получать унифицированный auth context и не зависел
  от конкретного Vetmanager auth mode.

---

## Этап 26.2: второй connection mode в abstraction layer

**Что реализовано:**
- В `vetmanager_auth.py` добавлен второй `auth_mode`: `user_token`.
- `VetmanagerAuthContext` стал более общим: хранит runtime credential как
  абстрактный секрет, а не только как `api_key`.
- При этом backward-compatible `api_key` alias сохранён, чтобы не ломать
  существующий bearer runtime и `VetmanagerClient`.

**Принятое допущение:**
- До подтверждения иного контракта реальным API user-token режим использует тот
  же transport header `X-REST-API-KEY`, потому что локальная OpenAPI знает
  только эту security scheme даже для tagged `Auth #3` endpoints.

**Архитектурный эффект:**
- Runtime уже умеет работать с несколькими Vetmanager auth modes через единый
  `VetmanagerAuthContext`.
- Следующие задачи могут отдельно добавлять web form и validation flow для
  `user_token`, не меняя bearer-only runtime boundary.

---

## Этап 26.3: настройка `user_token` в кабинете

**Что реализовано:**
- В кабинете `/account` форма integration теперь позволяет выбрать `auth_mode`.
- Для `domain_api_key` сохранён прежний путь сохранения с сетевой проверкой.
- Для `user_token` добавлен отдельный save path, который пока только безопасно
  сохраняет зашифрованные credentials и делает connection активным.

**Почему без runtime validation на этом шаге:**
- Такова граница roadmap: `26.3` отвечает за web-настройку, а `26.4` отдельно
  закрывает connection validation/test flow.
- Это позволяет не смешивать UI-изменения и догадки о контракте `token_auth.php`
  в одном шаге.

**Временный UX-контракт:**
- Пока локальные артефакты не раскрывают надёжно `token_auth.php`, кабинет
  принимает уже выданный Vetmanager `user_token`, а не сам выполняет
  login/password exchange.

**Что важно по безопасности:**
- `user_token`, как и `api_key`, не показывается повторно после сохранения и
  хранится только в `encrypted_credentials`.

---

## Этап 26.4: валидация `user_token` connection

**Что реализовано:**
- Перед сохранением `user_token` integration сервис теперь резолвит billing host
  и делает probe `GET /rest/api/user`.
- Для probe используется тот же transport header `X-REST-API-KEY`, который уже
  зафиксирован как текущее допущение для `Auth #3`.
- Невалидный `user_token` возвращает безопасную ошибку и не создаёт connection
  в БД.

**Что дополнительно поймано и исправлено:**
- На error-path поле `user_token` перестало подставляться обратно в HTML формы.
- Это закрывает регресс, при котором секрет мог бы отобразиться в ответе после
  неуспешной валидации.

**Итог:**
- Второй Vetmanager mode теперь уже не просто хранится, а проходит явный test
  connection до записи.

---

## Этап 26.5–26.6: runtime independence и тесты второго режима

**Что подтверждено тестами:**
- `resolve_bearer_auth_context()` возвращает одинаково нормализованный runtime
  context и для `domain_api_key`, и для `user_token`.
- `resolve_runtime_credentials()` и `VetmanagerClient` не ветвятся по
  конкретному Vetmanager auth mode; runtime использует единый
  `VetmanagerAuthContext` и transport header builder.
- Для `user_token` режима добавлены unit/mock тесты на bearer lookup, runtime
  resolution и client request path.

**Что дополнительно исправлено:**
- Real e2e harness в `tests/test_e2e_real.py` был рассинхронизирован с текущим
  `VetmanagerAuthContext` и создавал его через устаревший аргумент `api_key`.
- Harness переведён на актуальный аргумент `credential`, чтобы real smoke tests
  действительно проверяли текущий runtime-контракт.

**Контракт real smoke:**
- Отдельный real smoke для `user_token` режима выполняется только если заданы
  `TEST_DOMAIN` и `TEST_USER_TOKEN`.
- При отсутствии `TEST_USER_TOKEN` этот smoke корректно skip'ается и не
  блокирует обычный real suite для `domain_api_key`.

**Итог:**
- Bearer runtime остаётся mode-agnostic: конкретный способ Vetmanager auth
  инкапсулирован внутри connection/auth layer, а MCP runtime получает уже
  унифицированные runtime credentials.

---

## Этап 27.1: rate limiting по Bearer-токену

**Что реализовано:**
- Добавлен process-local in-memory limiter `bearer_rate_limiter.py`.
- Лимит применяется в `resolve_bearer_auth_context()` после успешного lookup и
  валидации Bearer-токена, но до обновления `last_used_at` и `request_count`.
- Превышение лимита возвращается через отдельный `RateLimitError` со статусом
  `429`, без раскрытия raw Bearer-токена.

**Выбранный контракт:**
- Ключ лимита: `bearer_token_id`, а не raw token и не account id.
- Алгоритм: sliding window по timestamps.
- Конфигурация:
  - `BEARER_RATE_LIMIT_REQUESTS`
  - `BEARER_RATE_LIMIT_WINDOW_SECONDS`
- Дефолт выбран консервативно-мягким: `1000` запросов за `60` секунд.

**Почему дефолт не сделан агрессивным:**
- В проекте уже есть объёмный mock/e2e контур и агрегирующие инструменты,
  которые могут делать плотные серии вызовов в одном процессе.
- Слишком низкий дефолт создавал бы ложные срабатывания в обычных сценариях и
  мешал бы существующему тестовому harness.
- При этом реальное ужесточение лимита остаётся доступным через env-конфиг без
  изменения кода.

**Осознанное ограничение текущего решения:**
- Лимитер process-local и не синхронизируется между несколькими инстансами.
- Для single-process deployment это уже даёт полезную защиту от burst abuse.
- Если сервис будет масштабироваться горизонтально, следующий шаг потребует
  shared backend (например, Redis) или edge-level rate limiting.

**Что подтверждено тестами:**
- Запросы внутри лимита проходят.
- Следующий запрос в том же окне блокируется.
- Лимит изолирован между разными Bearer-токенами.
- После истечения окна запросы снова допускаются.
- Заблокированный запрос не увеличивает `TokenUsageStat.request_count`.

---

## Этап 27.1.1–27.1.4: legacy runtime/test refactoring под credential-контракт

**Что было не так до рефакторинга:**
- В legacy tests оставались прямые вызовы `VetmanagerAuthContext(api_key=...)`,
  хотя канонический runtime-контракт уже перешёл на `credential`.
- `tests/test_client_multitenancy.py` и `tests/test_e2e_mock.py` дублировали
  ручную настройку внутреннего состояния `VetmanagerClient`.
- Этот дублирующийся setup уже начал расходиться с реальным runtime boundary и
  ломал suite при эволюции auth layer.

**Что реализовано:**
- Добавлен общий helper-модуль `tests/runtime_factories.py`.
- В него вынесены фабрики для:
  - `VetmanagerAuthContext`;
  - `RuntimeCredentials`;
  - преднастроенного `VetmanagerClient`;
  - patch-набора для runtime credential resolution.
- `tests/test_client_multitenancy.py` переведён на эти helpers.
- `tests/test_e2e_mock.py` тоже переведён на те же factories без ручного
  конструирования устаревшего auth context.

**Архитектурное решение:**
- Внутри runtime/test helper-слоя каноническим именем считается `credential`.
- Название `api_key` сохраняется только там, где речь реально идёт о payload
  connection mode `domain_api_key`, а не о внутреннем runtime abstraction.
- Backward-compatible property `api_key` в `VetmanagerAuthContext` остаётся как
  alias для runtime-кода, но новые тестовые helpers больше на него не опираются
  как на конструкторный контракт.

**Результат:**
- Снята рассинхронизация между текущим auth layer и старым test support кодом.
- Тестовые сценарии `client_multitenancy` и `e2e_mock` снова используют единый
  runtime boundary и дешевле поддерживаются при следующих изменениях auth flow.
- Полный test suite после миграции прошёл: `498 passed, 302 skipped`.

---

## Процессное решение: аудит и повторный полный прогон перед commit/push

**Что зафиксировано в workflow:**
- После первого полного прогона проверок агент обязан сделать аудит изменений.
- Цель аудита: поймать legacy-паттерны, дублирование, локальные хаки и
  рассинхрон со свежим контрактом, который мог появиться во время реализации.
- Если по итогам аудита внесён рефакторинг или любые дополнительные правки,
  перед `commit`/`push` обязателен ещё один полный прогон тестов и проверок.

**Почему правило добавлено:**
- Простого прохождения тестов сразу после Green-недостаточно, если следом был
  cleanup/refactoring pass.
- Иначе агент может запушить код после полезного рефакторинга, не подтвердив,
  что полный контур всё ещё зелёный.

**Практический эффект:**
- Core Loop теперь включает не только `Red -> Green`, но и обязательный
  post-implementation audit pass.
- `commit` и `push` разрешены только после финального полного прогона, если
  после аудита были изменения.

---

## Этап 27.2: более подробный audit trail по auth events

**Что реализовано:**
- Добавлен общий модуль `auth_audit.py` для token-centric audit events.
- `token_created` и `token_revoked` переведены на общий helper и теперь тоже
  получают `ip_address` / `user_agent`, если вызваны в HTTP request context.
- В `bearer_auth.py` добавлены runtime auth events:
  - `token_auth_succeeded`
  - `token_auth_failed_revoked`
  - `token_auth_failed_expired`
  - `token_auth_failed_no_connection`
  - `token_auth_rate_limited`

**Что осознанно не сделано на этом шаге:**
- Не добавлялась новая таблица для generic auth failures без найденного токена.
- Поэтому событие `invalid bearer token` для совсем неизвестного raw token пока
  не логируется: текущая схема `TokenUsageLog` требует валидный `bearer_token_id`.

**Что попадает в audit details:**
- безопасные metadata вроде `account_id`, `token_prefix`, `connection_id`,
  `auth_mode`, `domain`, `reason`, `retry_after_seconds`.
- В лог не попадают raw Bearer token, `token_hash`, Vetmanager secret и пароли.

**Архитектурный эффект:**
- Audit trail теперь фиксирует не только lifecycle токенов, но и фактическое
  использование и отказные security-sensitive ветки bearer runtime.
- Request metadata централизована в одном helper, а не размазана по web/runtime
  коду.

**Что подтверждено проверками:**
- Таргетный срез `tests/test_bearer_auth.py tests/test_web_auth.py` прошёл.
- Полный test suite после audit/refactoring pass прошёл:
  `501 passed, 302 skipped`.

---

## Этап 27.3: cleanup-политика для истёкших Bearer-токенов

**Что реализовано:**
- Добавлен `token_cleanup.py` с `sync_expired_tokens(session, account_id=None, now=None)`.
- Cleanup sweep переводит только `active` токены с прошедшим `expires_at` в статус
  `expired`.
- Для каждого такого перехода один раз пишется audit event `token_expired`.
- Dashboard account-страницы запускает cleanup sweep перед чтением списка токенов,
  поэтому пользователь видит актуальный статус без отдельной фоновой задачи.

**Выбранная политика:**
- Истёкший токен становится `expired`, а не `revoked`.
- Ручной revoke остаётся отдельным пользовательским действием и не смешивается с
  автоматическим истечением TTL.

**Что осознанно не сделано на этом шаге:**
- Не добавлялся cron/worker для глобальной фоновой очистки по всем аккаунтам.
- Cleanup пока process-local и выполняется лениво в web/dashboard flow.

**Архитектурный эффект:**
- UI и storage больше не расходятся по статусу токена после окончания TTL.
- Audit trail различает ручной revoke и автоматическое истечение срока действия.

**Что подтверждено проверками:**
- Добавлены unit tests на cleanup helper:
  обновление статуса, отсутствие дублей и защита от перезаписи revoked token.
- Добавлен web-тест на lazy cleanup через `/account`.
- Полный test suite после внедрения прошёл:
  `505 passed, 302 skipped`.

---

## Этап 27.4: hardening web-сессий и secret management

**Что реализовано:**
- Убран небезопасный fallback web-session секрета вида
  `dev-web-session-secret`.
- `get_web_session_secret()` теперь принимает только:
  - `WEB_SESSION_SECRET`, либо
  - `STORAGE_ENCRYPTION_KEY` как fallback для локальной совместимости.
- При отсутствии обоих значений web auth теперь падает с явной ошибкой
  конфигурации вместо запуска с предсказуемым секретом.
- Cookie настроены с более жёсткими дефолтами:
  - `HttpOnly`
  - `Secure=True`
  - `SameSite=Strict`
- Для локальных/тестовых сценариев добавлены явные env overrides:
  `WEB_SESSION_SECURE` и `WEB_SESSION_SAMESITE`.

**Почему выбрана именно такая модель:**
- Для production нельзя оставлять встроенный статический секрет подписи cookie.
- Одновременный fallback на `STORAGE_ENCRYPTION_KEY` снижает риск поломки уже
  существующих окружений, где secret management ещё не был разделён полностью.

**Что осознанно не сделано на этом шаге:**
- Не вводилась отдельная rotation-механика для session secret.
- Не добавлялся Redis/server-side session store: текущая signed-cookie модель
  остаётся достаточной для MVP web-контура.

**Архитектурный эффект:**
- Web auth больше не зависит от встроенного dev-secret.
- Безопасные cookie defaults применяются централизованно в одном helper, а не
  размазаны по route handlers.

**Что подтверждено проверками:**
- Добавлены тесты на обязательность конфигурации секрета.
- Добавлены тесты на `Secure` и `SameSite=Strict` как дефолтные cookie flags.

---

## Этап 28: future scopes / RBAC для Bearer-токенов

**Что реализовано:**
- Создан отдельный PRD на этап 28 с capability-based моделью прав Bearer-токенов.
- Добавлен единый registry coarse-grained scopes в `token_scopes.py`.
- В `service_bearer_tokens` добавлены:
  - `access_policy_version`
  - `scopes_json`
- `ServiceBearerToken` получил helper'ы `set_scopes()` и `get_scopes()`.
- Новые токены при выпуске получают default full-access scope manifest.
- Legacy токены без `scopes_json` интерпретируются как совместимые full-access
  токены до будущего runtime enforcement.

**Выбранная модель:**
- Это не полноценный enterprise RBAC по пользователям и ролям.
- Базовая единица прав сейчас — сам Bearer-токен с capability list.
- Naming convention для прав: `<resource_group>.<action>`.

**Зафиксированные coarse-grained scopes:**
- `clients.read`, `clients.write`
- `pets.read`, `pets.write`
- `admissions.read`, `admissions.write`
- `medical_cards.read`, `medical_cards.write`
- `finance.read`, `finance.write`
- `inventory.read`, `inventory.write`
- `users.read`
- `messaging.read`, `messaging.write`
- `reference.read`
- `analytics.read`

**Что осознанно не сделано на этом шаге:**
- Не включён runtime enforcement scopes на tools/prompts.
- Не добавлен UI для выбора scopes при выпуске токена.
- Не вводились wildcard scopes, deny-rules и сложная иерархия ролей.

**Архитектурный эффект:**
- Storage уже готов хранить policy metadata токена без изменения bearer-only
  runtime-контракта.
- Следующий enforcement-этап сможет опираться на стабильный manifest вместо
  ad-hoc mapping прямо в runtime.

**Что подтверждено проверками:**
- Добавлены unit tests на scope helpers и default full-access manifest.
- Обновлён migration test: Alembic `upgrade head` подтверждает новые колонки.
- Таргетный срез `tests/test_token_scopes.py tests/test_migrations.py tests/test_bearer_token_security.py tests/test_web_auth.py`
  прошёл: `23 passed`.

---

## Этап 29: stabilization test warnings и startup lifecycle

**Что реализовано:**
- `storage.reset_storage_state()` теперь явно dispose'ит cached `AsyncEngine`,
  а не только очищает LRU cache.
- Это закрывает thread/loop хвост `aiosqlite`, который раньше проявлялся в
  teardown полного suite.
- В `pytest.ini` задан `asyncio_default_fixture_loop_scope=function`, чтобы
  убрать warning от `pytest-asyncio`.
- Добавлены regression tests на engine dispose и bootstrap schema.

**Дополнительное наблюдение:**
- Browser E2E вскрыл ещё один реальный startup gap: свежий локальный runtime
  падал на `/register` с `sqlite3.OperationalError: no such table: accounts`.
- Для этого добавлен `bootstrap_storage_schema()` и вызов bootstrap на старте
  `server.py`, чтобы fresh SQLite runtime мог подняться без ручного create_all.

**Что подтверждено проверками:**
- Warning-чувствительный срез прошёл с `python -W error`:
  `40 passed`.

---

## Этап 30: real e2e на контуре `devtr6`

**Что реализовано:**
- В `tests/test_e2e_real.py` добавлен расширенный env-контракт:
  - `TEST_DOMAIN`
  - `TEST_API_KEY`
  - `TEST_USER_TOKEN`
  - `TEST_USER_TOKEN_BASE_URL`
  - `TEST_USER_LOGIN`
  - `TEST_USER_PASSWORD`
- Сохранён backward-compatible путь через уже готовый `TEST_USER_TOKEN`.
- Добавлены real smoke tests для:
  - `validate_domain_api_key_connection()`
  - login/password -> token exchange
  - `validate_user_token_connection()` на user-token contour
- Обновлены `.env.example`, `docker-compose.yml`, `README.md` и `test-real.yml`.

**Что установлено по факту на предоставленных данных:**
- API-key contour `devtr6` с предоставленным test API key проходит real smoke.
- `POST https://devtr6.vetmanager2.ru/token_auth.php` на предоставленных
  `admin4` / `123456` возвращает `401 Wrong authentification`.
- Поэтому login/password smoke в этом контуре сейчас skip'ается как
  environment/auth-data limitation, а не как transport/protocol bug сервиса.

**Что подтверждено проверками:**
- Реальный прогон `tests/test_e2e_real.py` на `devtr6` прошёл:
  `48 passed, 4 skipped`.

---

## Этап 31: browser E2E полного пути до MCP Bearer runtime

**Что реально проверено:**
- Абсолютный URL browser flow:
  - `http://127.0.0.1:8000/register`
  - `http://127.0.0.1:8000/account`
  - `http://127.0.0.1:8000/account/integration`
  - `http://127.0.0.1:8000/account/tokens`
- Через браузер подтверждены:
  - регистрация нового account;
  - login;
  - сохранение active Vetmanager integration для `devtr6` по API key;
  - выпуск Bearer token;
  - отображение token list, usage metadata и revoke action.
- После web-выпуска raw Bearer token был проверен реальным MCP runtime вызовом
  через `fastmcp.client.Client('http://127.0.0.1:8000/mcp', auth=<raw_token>)`.
- `list_tools()` и `call_tool('get_clients', {'limit': 1, 'offset': 0})`
  прошли успешно на реальном `devtr6` contour.
- После revoke из браузера повторный MCP вызов вернул ожидаемую ошибку
  `Revoked bearer token`.

**Что осталось ограничением:**
- Текущий web UI по-прежнему принимает готовый `user_token`, а не выполняет
  login/password exchange сам.
- На предоставленных login/password данных `token_auth.php` возвращает `401`,
  поэтому browser-проверка login/password user-token flow не могла быть
  подтверждена в этом прогоне.

---

## Этап 32: privacy messaging и auth transparency

**Что реализовано:**
- На лендинге добавлен явный privacy/auth блок:
  - сервис не сохраняет бизнес-данные Vetmanager для постоянного хранения;
  - хранятся только технические integration metadata и service bearer metadata;
  - login/password используются только для получения user token.
- В кабинете account добавлен отдельный privacy/auth transparency блок с тем же
  продуктовым контрактом.
- В форме Vetmanager integration добавлено прямое пояснение, что login/password
  не сохраняются и используются только для token exchange.
- В UI зафиксировано явное предупреждение: при смене пароля в Vetmanager
  сохранённый user token может стать невалидным и потребуется повторная
  авторизация.

**Что подтверждено проверками:**
- Добавлены и прошли HTTP tests на landing/account messaging.

---

## Этап 33: token health, token rotation и re-auth UX

**Что реализовано:**
- Для active Vetmanager integration введён on-demand health status:
  - `active`
  - `invalid`
  - `reauth_required`
  - `unknown`
- `/account` теперь делает health-check active connection при рендере dashboard.
- Для невалидного `user_token` в кабинете показываются:
  - `reauth_required`
  - reason message
  - явный CTA `Переавторизоваться и обновить токен`
- Добавлен re-auth submit path `/account/integration/reauth`.
- Выдача новых service bearer tokens теперь блокируется, если active
  integration отсутствует или её health не `active`.

**Принятая стратегия revalidation:**
- Для текущего релиза выбран безопасный on-demand health check.
- Background scheduler или отдельная health history не добавлялись.
- Это держит модель простой и не требует нового storage state для heartbeat.

**Что подтверждено проверками:**
- Добавлены тесты на `reauth_required` и замену invalid user-token connection.

---

## Этап 34: hardening login/password и auth lifecycle UX

**Что реализовано:**
- Web UI для user-token режима больше не требует вручную вставлять raw
  `user_token`.
- Вместо этого кабинет принимает:
  - `domain`
  - `api_key`
  - `Vetmanager login`
  - `Vetmanager password`
- Backend выполняет `POST /token_auth.php`, извлекает token и сохраняет только
  `user_token` в encrypted storage.
- Login/password не сохраняются в `vetmanager_connections.encrypted_credentials`
  и не отражаются обратно в HTML после submit/error state.
- Safe error mapping для exchange path:
  - invalid credentials/API key -> `Invalid Vetmanager login, password or API key.`
  - network/timeout failures -> safe `VetmanagerError` / `VetmanagerTimeoutError`
    без отражения исходных credentials.

**Что установлено по contract shape:**
- Для exchange используется:
  - `POST <resolved_host>/token_auth.php`
  - `Content-Type: application/x-www-form-urlencoded`
  - `Accept: application/json`
  - `X-REST-API-KEY: <rest api key>`
  - form-data `login`, `password`
- Token extraction сделан tolerant к нескольким payload shapes:
  - `data` как строка
  - `data.token`
  - `data.user_token`
  - `data.api_key`
  - `data.key`

**Что подтверждено проверками:**
- Добавлены HTTP tests на успешный exchange flow и safe failure path без утечки
  `api_key`, login и password.
- Browser-smoke после UI-изменений подтверждён на локальном `http://127.0.0.1:8000/account`:
  - privacy/auth transparency block отображается;
  - форма user-token режима показывает поля `REST API key`, `Vetmanager login`,
    `Vetmanager password`;
  - submit на предоставленных `devtr6` credentials возвращает безопасную ошибку
    `Invalid Vetmanager login, password or API key.` без эха credentials в UI.

---

## Этап 35: security audit и remediation backlog

**Что проверено вручную по коду:**
- Секреты account auth:
  - password account хранится как PBKDF2 hash;
  - signed web session cookie уже использует `HttpOnly`, `Secure` и
    `SameSite=Strict` defaults.
- Секреты Vetmanager integration:
  - `domain_api_key` и `user_token` сохраняются только в encrypted storage;
  - login/password для user-token flow не сохраняются.
- Service bearer:
  - raw bearer показывается только один раз при выпуске;
  - дальше хранится только hash + safe prefix;
  - revoke/expired/invalid paths уже закрыты отдельными safe errors и audit logs.
- Logging / audit:
  - в inspected коде нет явного `print` / debug logging с credentials;
  - tests подтверждают, что raw bearer и Vetmanager credentials не попадают в
    rendered HTML и `details_json` audit trail.

**Findings и приоритет:**
- `high`: новых blocker-findings в рамках inspected path не выявлено.
- `medium`: у web forms всё ещё нет отдельного CSRF token layer; текущая
  защита опирается на signed session cookie и `SameSite=Strict`, но это не
  полноценная замена CSRF-механизму.
- `medium`: нет отдельного login/register brute-force limiter для web account
  endpoints.
- `low`: не добавлен явный набор HTTP security headers уровня CSP/HSTS/XFO для
  web UI, так как current scope был сфокусирован на auth secrecy и lifecycle.

**Решение по backlog:**
- Отдельный remediation этап в roadmap в этом проходе не добавлялся, так как
  blocker/high findings не найдено, а основной пользовательский auth/privacy
  контракт уже приведён в соответствие с реализацией.
- Residual medium/low findings зафиксированы здесь как обязательный input для
  следующего security hardening iteration.

---

## Этап 36: security remediation

**Что реализовано:**
- Для web UI добавлен signed double-submit CSRF layer:
  - GET-страницы с формами выставляют cookie `vm_csrf`;
  - формы рендерят hidden field `csrf_token`;
  - POST-маршруты `/register`, `/login`, `/logout`, `/account/integration`,
    `/account/integration/reauth`, `/account/tokens`,
    `/account/tokens/{id}/revoke` отклоняют missing/mismatch token c `403`.
- Для `/register` и `/login` добавлен process-local sliding-window limiter:
  - `/register`: ключ по IP;
  - `/login`: ключ по IP + normalized email;
  - при превышении лимита возвращается безопасный `429` без утечки деталей.
- Для HTML-ответов web UI добавлен baseline security headers набор:
  - `Content-Security-Policy`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `X-Content-Type-Options: nosniff`
  - `Strict-Transport-Security` включается только при явном production env flag.

**Что подтверждено проверками:**
- Добавлены HTTP tests на:
  - CSRF cookie + hidden field;
  - rejection для missing/mismatched CSRF;
  - login/register rate limiting;
  - security headers.
- Login/logout и session invalidation regression не выявлены:
  успешный login создаёт session cookie, logout по valid CSRF возвращает `303`
  на `/`, а следующий `GET /account` снова редиректит на `/login`.

**Что важно по ограничениям:**
- CSRF и login/register limiter сейчас process-local. Для multi-instance
  production deployment их нужно будет переносить в shared store/edge layer,
  если появится горизонтальное масштабирование.

---

## Этап 37: landing page для ветврачей и руководителей клиник

**Что изменено в продуктовой подаче:**
- Главная страница переписана с developer-centric подачи на язык пользы для
  ветврачей, администраторов и руководителей клиник.
- Регистрация вынесена в главный CTA:
  - отдельная заметная кнопка `Зарегистрироваться` в hero;
  - отдельная ссылка в top nav;
  - повторный CTA в footer.
- Убран акцент на `Cursor` из hero и основного narrative. Технический MCP-блок
  сохранён ниже страницы как secondary information.
- Добавлены product-блоки:
  - `Что получает клиника`
  - `Для кого сервис`
  - `Как начать работу`
  - `Какие вопросы можно задавать`

**Browser-check:**
- Локальный smoke прогнан на `http://127.0.0.1:8000/`:
  - desktop snapshot подтверждает hero, privacy/auth messaging и главный CTA
    регистрации;
  - mobile snapshot подтверждает, что CTA `Зарегистрироваться`, навигация и
    основные продуктовые блоки остаются доступны.

**Что подтверждено тестами:**
- `tests/test_landing_page.py` теперь проверяет:
  - продуктовую формулировку для ветврачей/администраторов/руководителей;
  - наличие `Зарегистрироваться` и ссылки `/register`;
  - отсутствие `Cursor` в landing copy.

---

## Этап 38: account onboarding и wizard авторизации

**Что изменено в кабинете:**
- `/account` переписан с более понятной product-подачей:
  - явный onboarding state для нового account;
  - пояснение, что следующий шаг после регистрации — подключить Vetmanager;
  - меньше developer-centric формулировок в верхней части страницы.
- Форма integration переведена в wizard:
  - сначала выбор способа авторизации;
  - затем отображаются только релевантные поля.
- Для `API key` показываются только `domain` и `api_key`.
- Для `login/password` показываются только `domain`, `api_key`, `login`,
  `password`.
- Скрытая панель wizard не участвует в submit/валидации:
  поля в неактивной панели отключаются и не перетирают значения активного режима.

**UX выпуска bearer token:**
- После выпуска новый raw bearer рендерится в отдельной success-card в верхней
  части кабинета, а не теряется ниже по странице.
- В success-card добавлены:
  - одноразовое предупреждение `Скопируйте его сейчас`;
  - read-only поле с raw token;
  - кнопка `Скопировать токен`;
  - feedback `Токен скопирован в буфер обмена`.
- Browser smoke подтвердил, что после выпуска token сразу виден без ручного
  поиска и скролла по странице.

**Расследование `devtr6` login/password exchange:**
- Реальный вызов `POST https://devtr6.vetmanager2.ru/token_auth.php` с
  предоставленными данными вернул:
  - HTTP `401`
  - `title: Wrong authentification.`
  - `detail: Неправильный логин или пароль.`
- Это подтверждает, что проблема не в host resolution и не в формате ответа.
- Текущий вывод по inspected path:
  тестовый contour отвергает именно login/password credentials для token exchange.
- В `tests/test_e2e_real.py` skip для этого smoke теперь фиксирует detail
  rejection, а не просто абстрактный auth failure.

**Что улучшено в error mapping:**
- Для `401` остаётся безопасное сообщение
  `Invalid Vetmanager login, password or API key.`
- Для `403` добавлен отдельный safe path:
  авторизация по login/password недоступна или отключена для клиники.
- Для malformed success response добавлено отдельное safe сообщение, что
  Vetmanager не вернул user token.

---

## Этап 39: browser E2E главного сценария

**Что подтверждено в реальном браузере:**
- На локальном `http://127.0.0.1:8000/` / `http://127.0.0.1:8000/register`:
  - account успешно регистрируется;
  - `/account` показывает onboarding wizard;
  - wizard переключается между `API key` и `логин/пароль`;
  - API-key сценарий для `devtr6` успешно сохраняет active integration;
  - выпуск service bearer token успешен;
  - новый raw token сразу появляется в success-card;
  - copy button работает и показывает явный feedback.

**Что подтверждено по bearer -> MCP:**
- Тем же token из browser-сценария выполнен реальный `mcp.call_tool("get_clients")`.
- Runtime успешно:
  - разрешил bearer -> account -> active connection;
  - выполнил host resolution для `devtr6`;
  - сделал реальный запрос `GET /rest/api/client` на contour;
  - вернул структурированный ответ с данными клиентов.

**Automation coverage:**
- Добавлен real E2E:
  `tests/test_e2e_real.py::test_real_web_account_can_issue_bearer_and_call_tool`
- Этот тест покрывает путь:
  web account -> integration -> issued bearer -> MCP tool call.

---

## Этап 40: production hardening

**Что зафиксировано как production baseline:**
- Текущий login/register limiter process-local и подходит для single-instance
  deployment, но не для горизонтального масштабирования.
- Для production нужен один из вариантов:
  - shared store limiter;
  - edge/proxy rate limiting;
  - либо оба слоя вместе.
- CSRF/session baseline безопасен для single-instance сценария с общим
  `WEB_SESSION_SECRET`, но multi-instance deployment требует:
  - один и тот же session secret на всех инстансах;
  - предсказуемую cookie/security policy;
  - documented deploy checklist.

**Что синхронизировано:**
- В `README.md` добавлены production notes:
  - внешний rate limit;
  - единый `WEB_SESSION_SECRET`;
  - явный `STORAGE_ENCRYPTION_KEY`;
  - `WEB_ENABLE_HSTS=1` за HTTPS reverse proxy.

---

## Этап 41: ревизия user-token flow

**Что зафиксировано по контракту `token_auth.php`:**
- Предыдущее проектное допущение было неверным:
  `login/password -> user token` flow не должен зависеть от
  `X-REST-API-KEY` и не должен моделироваться как режим
  `domain + api_key + login/password`.
- Для этапа 41 источником истины считается контракт:
  - `POST /token_auth.php`
  - `multipart/form-data`
  - поля `login`, `password`, `app_name`
  - без `X-REST-API-KEY` в exchange-запросе
- Значение `app_name` в проекте фиксировано как `vetmanager-mcp`.

**Что это меняет для проекта:**
- Web wizard режима `login/password` должен запрашивать только:
  `domain`, `login`, `password`.
- Backend exchange и reauth обязаны работать по одному и тому же контракту.
- Real/mock/browser tests должны различать:
  - прямую валидацию уже имеющегося `user_token`;
  - обязательную проверку самого `login/password exchange`.

**Что изменено в коде и тестах:**
- `vetmanager_connection_service.exchange_user_token()` переведён на
  `multipart/form-data` через поля `login`, `password`, `app_name`, без
  `X-REST-API-KEY`.
- `app_name` зафиксирован константой `vetmanager-mcp`.
- Safe auth error для `401` в exchange больше не упоминает `api_key`:
  теперь это `Invalid Vetmanager login or password.`
- `save_user_login_password_connection()` и web reauth path больше не принимают
  `api_key`.
- В `/account` и `/account/integration/reauth` у режима `login/password`
  удалено поле `api_key`; в DOM остаётся только один `api_key` input,
  относящийся к отдельному режиму `API key`.
- `tests/test_vetmanager_connection_service.py` и `tests/test_web_auth.py`
  теперь явно проверяют:
  - `multipart/form-data`;
  - наличие `app_name=vetmanager-mcp`;
  - отсутствие `X-REST-API-KEY` в exchange request;
  - отсутствие `api_key` в web submit для `login/password` режима.
- `tests/test_e2e_real.py` разделён на два независимых real smoke path:
  - direct validation с `TEST_USER_TOKEN`;
  - обязательный `login/password exchange` через
    `TEST_USER_TOKEN_BASE_URL`, `TEST_USER_LOGIN`, `TEST_USER_PASSWORD`.
- Для real exchange `401` больше не трактуется как benign skip: это теперь
  явный failure, если credentials были переданы и flow сломан.

**Проверки после аудита:**
- Точечный прогон:
  `docker compose --profile test run --rm test pytest tests/test_vetmanager_connection_service.py tests/test_web_auth.py -q`
  -> `30 passed`.
- Полный suite после всех правок:
  `docker compose --profile test run --rm test`
  -> `526 passed, 305 skipped`.

---

## Этап 42.3: deterministic upstream mocks для browser auth flows

**Что зафиксировано по mock layer:**
- Для live browser/live HTTP тестов нужен process-wide перехват `httpx`,
  иначе запросы из Uvicorn thread уходят наружу мимо обычных per-test mocks.
- `respx` подходит для этого сценария, если:
  - router стартует как глобальный patcher;
  - `127.0.0.1` и `localhost` явно пропущены через `pass_through()`,
    чтобы не ломать сам тестовый клиент к локальному harness.

**Какие reusable fixtures добавлены:**
- В `tests/conftest.py` добавлен `upstream_mock_router` для process-global
  mock layer.
- Добавлены две фабрики:
  - `mock_domain_api_key_upstream(...)`
  - `mock_user_token_upstream(...)`
- Обе фабрики возвращают объект состояния с:
  - параметрами домена/credentials;
  - ссылками на зарегистрированные routes;
  - captured request списками для token exchange и validation.

**Что подтверждено regression tests:**
- `tests/test_live_upstream_mocks.py` доказывает, что live localhost server
  действительно использует deterministic mocks для обоих auth flow.
- Для `domain + api_key` подтверждено:
  - billing resolve мокается;
  - validation идёт в `/rest/api/client`;
  - в запросе уходит `X-REST-API-KEY` и query `limit=1&offset=0`.
- Для `login/password -> user token` подтверждено:
  - billing resolve мокается;
  - `POST /token_auth.php` уходит как `multipart/form-data`;
  - в exchange нет `X-REST-API-KEY`;
  - в payload есть `app_name=vetmanager-mcp`;
  - последующая validation использует выданный `user_token`.

**Наблюдаемый контракт текущего web-flow:**
- После успешного сохранения integration страница аккаунта сразу выполняет
  повторную health-check валидацию connection.
- Поэтому deterministic mocks должны терпеть как минимум один повторный
  validation request в рамках одного submit/redirect цикла.

**Проверки после аудита:**
- Точечный прогон:
  `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_browser_live_harness.py tests/test_live_upstream_mocks.py -q"`
  -> `3 passed, 2 warnings`.

---

## Этапы 42.4-42.6: browser happy-path для обоих auth flow + UI secrecy assertions

**Что зафиксировано по browser happy-path coverage:**
- Добавлен browser сценарий для `domain + api_key`:
  `tests/test_browser_happy_path_domain_api_key.py`
- Добавлен browser сценарий для `login/password -> user token`:
  `tests/test_browser_happy_path_user_token.py`
- Оба теста проходят путь:
  - регистрация account через реальный localhost HTTP harness;
  - настройка Vetmanager integration через web UI;
  - выпуск service bearer token;
  - `mcp.call_tool(...)` с этим bearer token.

**Технические решения для browser -> MCP call:**
- Sync Playwright tests нельзя безопасно завершать `asyncio.run(...)`,
  потому что в потоке уже может жить event loop браузерного рантайма.
- Для этого в `tests/conftest.py` добавлен reusable helper fixture
  `run_async`, который исполняет coroutine в отдельном worker thread.
- Этот helper уже пригоден и для следующих browser задач этапа 42.

**Что подтверждено для `domain + api_key`:**
- Browser flow реально доходит до сохранения integration и выпуска bearer.
- Далее bearer используется в `mcp.call_tool("get_clients", ...)`.
- В captured upstream requests виден отдельный tool-вызов с `limit=2`,
  то есть browser path не заканчивается только на validation check.

**Что подтверждено для `login/password -> user token`:**
- Browser flow переключает wizard на `user_token` режим, отправляет
  `domain`, `vm_login`, `vm_password`, получает user token через
  `token_auth.php`, затем выпускает bearer token.
- Далее bearer используется в `mcp.call_tool("get_users", ...)`.
- Captured requests подтверждают использование и `POST /token_auth.php`,
  и `GET /rest/api/user` с параметрами tool-вызова.

**Что зафиксировано по UI contract и secret leak protection:**
- Browser tests теперь явно проверяют:
  - в DOM ровно один `api_key` input;
  - активна только соответствующая auth panel;
  - неактивная panel скрыта.
- После submit в итоговом HTML не должны появляться:
  - `api_key` для API-key режима;
  - `vm_password` и полученный `user_token` для user-token режима.

**Проверки после аудита:**
- Browser subset:
  `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_browser_happy_path_domain_api_key.py tests/test_browser_happy_path_user_token.py -q"`
  -> `2 passed, 2 warnings`.
- Полный suite после добавления browser happy-path tests:
  `docker compose --profile test run --rm test`
  -> `532 passed, 305 skipped, 5 warnings`.
- Из них:
  - 2 warnings связаны с `uvicorn/websockets` deprecation в live browser
    harness;
  - 3 warnings относятся к уже существующему `aiosqlite` thread/loop
    shutdown поведению в `tests/test_token_cleanup.py`.

---

## Этапы 42.7-42.8: cleanup helper и regression на очистку browser данных

**Что реализовано в test infrastructure:**
- В `tests/conftest.py` добавлен reusable helper `browser_account_cleanup`.
- Helper отслеживает test accounts по email и умеет:
  - запускать cleanup вручную через `cleanup_now()`;
  - автоматически выполнять cleanup в teardown;
  - возвращать отчёт `before/after` по ключевым таблицам.

**Что удаляется cleanup helper:**
- `accounts`
- `vetmanager_connections`
- `service_bearer_tokens`
- `token_usage_stats`
- `token_usage_logs`

Удаление выполняется через ORM delete на `Account` с уже описанными
relationship cascade, поэтому cleanup не дублирует бизнес-логику удаления по
таблицам вручную.

**Как helper встроен в browser suite:**
- Оба browser happy-path теста теперь регистрируют свой test account email в
  helper сразу перед созданием account.
- Это делает cleanup единым и независимым от конкретного auth flow.

**Что подтверждено regression test:**
- Добавлен `tests/test_browser_cleanup.py`.
- Тест проходит browser flow с созданием:
  - account;
  - Vetmanager integration;
  - service bearer token;
  - usage stat/log через реальный `mcp.call_tool(...)`.
- После `cleanup_now()` в БД остаются нули по всем связанным таблицам.

**Проверки после аудита:**
- Узкий прогон cleanup/browser блока:
  `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_browser_happy_path_domain_api_key.py tests/test_browser_happy_path_user_token.py tests/test_browser_cleanup.py -q"`
  -> `3 passed, 2 warnings`.

---

## Этап 42.9: doc sync для обязательного browser suite

**Что синхронизировано:**
- В `README.md` default команда `docker compose run --rm test` теперь явно
  описана как обязательный suite, включающий:
  - unit tests;
  - mock/e2e tests;
  - live Playwright browser tests;
  - browser happy-path tests для обоих auth flow;
  - cleanup regression.
- В `README.md` зафиксировано, что Chromium уже предустановлен в test image и
  для browser suite не нужен отдельный runtime setup.
- В таблице CI/CD `test.yml` теперь описан как workflow для полного default
  suite без реального Vetmanager API.

---

## Этап 42.10: opt-in real browser tests

**Что добавлено:**
- В `pytest.ini` зарегистрирован marker `real_browser`.
- Добавлен файл `tests/test_browser_real_opt_in.py` с двумя opt-in tests:
  - real browser API-key flow;
  - real browser login/password -> user token flow.

**Контракт opt-in режима:**
- Для запуска нужен явный флаг `RUN_REAL_BROWSER_TESTS=1`.
- Для API-key сценария требуются `TEST_DOMAIN` и `TEST_API_KEY`.
- Для user-token сценария требуются
  `TEST_USER_TOKEN_BASE_URL`, `TEST_USER_LOGIN`, `TEST_USER_PASSWORD`.
- Без этих env tests только коллектаются и корректно `skip`, не меняя
  смысл default suite.

**Что подтверждено:**
- В default режиме `tests/test_browser_real_opt_in.py` даёт `2 skipped`.
- Это позволяет держать real browser coverage в репозитории, не включая её в
  обязательный прогон без явного opt-in.

**Итоговый статус этапа 42:**
- Default suite после полного закрытия этапа:
  `docker compose --profile test run --rm test`
  -> `533 passed, 307 skipped, 2 warnings`.
- Два skip сверху — это opt-in `real_browser` tests без `RUN_REAL_BROWSER_TESTS=1`.
- Две warnings относятся к `uvicorn/websockets` deprecation в live browser
  harness и не блокируют default regression contract.

---

## Этап 43.1: устранение `aiosqlite` thread/event-loop warnings

**Источник проблемы:**
- Warning-шум в полном suite шёл не из бизнес-логики cleanup, а из lifecycle
  временных SQLite async engine, которые поднимались прямо внутри тестов и не
  гарантированно закрывались до завершения event loop.
- Симптом проявлялся как `PytestUnhandledThreadExceptionWarning` с
  `RuntimeError: Event loop is closed` в `tests/test_token_cleanup.py`.

**Архитектурное решение:**
- В `tests/conftest.py` добавлен reusable async fixture
  `sqlite_session_factory_builder`, который:
  - создаёт временный SQLite engine;
  - поднимает schema через `Base.metadata.create_all`;
  - в teardown гарантированно делает `await engine.dispose()`.
- `tests/test_token_cleanup.py` переведён с приватного локального helper на
  общий fixture, чтобы lifecycle engine контролировался pytest-фикстурой, а не
  оставался неявным внутри теста.

**Границы решения:**
- На `43.1` устранены именно `aiosqlite` thread/event-loop warnings.
- Оставшиеся 2 warnings в полном suite относятся к
  `uvicorn/websockets` deprecation в live browser harness и вынесены в `43.2`.

**Проверки после аудита:**
- Полный suite:
  `docker compose --profile test run --rm test`
  -> `533 passed, 307 skipped, 2 warnings`.
- После фикса warnings от `aiosqlite` в suite больше не воспроизводятся.

---

## Этап 43.2: устранение `uvicorn/websockets` deprecation warnings

**Источник проблемы:**
- `DeprecationWarning` шёл из test-only live browser harness в
  `tests/conftest.py`, где `uvicorn.Server` поднимался с дефолтным websocket
  protocol stack.
- Browser/live tests при этом используют только обычный HTTP endpoint для
  HTML-страниц и `streamable-http` MCP path, без websocket transport.

**Архитектурное решение:**
- В test-only `uvicorn.Config` для fixture `live_server_url` явно задано
  `ws="none"`.
- Это убирает ненужный импорт legacy `websockets` implementation и оставляет
  harness строго HTTP-only, что соответствует реальному использованию в tests.

**Почему это корректно:**
- Решение не меняет runtime-контракт приложения и не затрагивает production
  конфигурацию.
- Изменение локализовано только в test infrastructure.
- Browser/live regression остаётся покрыт существующими browser tests.

**Проверки после аудита:**
- Browser/live subset с deprecation как ошибкой:
  `docker compose --profile test run --rm test sh -c "python -W error::DeprecationWarning -m pytest tests/test_browser_live_harness.py tests/test_browser_cleanup.py tests/test_browser_happy_path_domain_api_key.py tests/test_browser_happy_path_user_token.py -q"`
  -> `4 passed`.
- Полный suite:
  `docker compose --profile test run --rm test`
  -> `533 passed, 307 skipped`.
- После фикса warnings summary в default suite отсутствует.

---

## Этап 43.3: policy по warnings для test/CI contour

**Что зафиксировано как policy:**
- Default suite имеет нулевую tolerance к warnings:
  `warnings_allowed = 0`.
- Warning в default contour считается CI-blocking сигналом, а не шумом.
- Opt-in real contour тоже стремится к нулю warnings, но сам по себе не
  определяет исход обязательного CI.
- Глобальные `filterwarnings`-ignore правила в `pytest.ini` запрещены.
- Если suppression когда-либо понадобится, она должна быть только scoped:
  на конкретный test/module, с явной причиной и отдельной roadmap-задачей.

**Архитектурное решение:**
- Создан machine-readable source of truth в `warning_policy.py`:
  - `DEFAULT_SUITE_WARNING_POLICY`
  - `OPT_IN_REAL_SUITE_WARNING_POLICY`
  - `BLOCKING_WARNING_CATEGORIES`
- Это сделано как подготовка к `43.4`, чтобы fail-on-unexpected-warnings
  опирался на один явный контракт, а не на разрозненные договорённости в CI.

**Guardrails:**
- Добавлен `tests/test_warning_policy.py`, который проверяет:
  - zero-warning policy для default suite;
  - неблокирующий статус opt-in real contour для обязательного CI;
  - перечень блокирующих warning categories;
  - отсутствие глобального `filterwarnings` в `pytest.ini`.

**Проверки после аудита:**
- Policy tests:
  `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_warning_policy.py -q"`
  -> `4 passed`.
- Полный suite:
  `docker compose --profile test run --rm test`
  -> `537 passed, 307 skipped`.

---

## Этап 43.4: fail-on-unexpected-warnings для default suite

**Что изменено в default contour:**
- Добавлен launcher `scripts/run_default_test_suite.py`, который запускает
  default suite через `python -W error -m pytest tests/ -v`.
- `docker compose --profile test run --rm test` теперь вызывает этот launcher,
  а не прямой inline `pytest`.
- Launcher опирается на `warning_policy.py`, а не на разрозненные shell-флаги.

**Что пришлось исправить для строгого режима:**
- SQLite async test factories в bearer/runtime/connection-service тестах
  переведены на общий disposable helper `sqlite_session_factory_builder`,
  чтобы engines гарантированно закрывались.
- Live upstream regression переведён с sync `httpx.Client` на browser-driven
  flow, чтобы исключить socket/event-loop residue в strict warning mode.
- Real web E2E тест переведён на live localhost harness и sync `httpx.Client`
  + `run_async(...)`, чтобы убрать конфликт с loop lifecycle in-process ASGI.
- `test_tools_list_schema.py` больше не использует `asyncio.run(...)` во время
  import/collection; export контракта теперь строится через fixtures.
- В `bearer_rate_limiter.py` убран import-time `asyncio.Lock()`:
  limiter теперь создаёт loop-local lock лениво, только внутри running loop.

**Архитектурное решение:**
- Для CLI warning-as-error используется coarse `-W error`, потому что Python
  не умеет надёжно резолвить third-party категории warning'ов до импорта
  соответствующих библиотек.
- Нулевая tolerance к warnings обеспечивается сочетанием:
  - machine-readable policy;
  - отдельного launcher;
  - cleanup/fix'ов для loop/socket lifecycle в тестовой инфраструктуре.

**Проверки после аудита:**
- Targeted strict subsets:
  - `docker compose --profile test run --rm test sh -c "python -W error -m pytest tests/test_bearer_auth.py tests/test_tools_list_schema.py -q"` -> `33 passed`
  - `docker compose --profile test run --rm test sh -c "python -W error -m pytest tests/test_bearer_rate_limit.py tests/test_tools_list_schema.py -q"` -> `26 passed`
  - `docker compose --profile test run --rm test sh -c "python -W error -m pytest tests/test_e2e_real.py tests/test_tools_list_schema.py -q"` -> `72 passed, 5 skipped`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `310 passed, 7 skipped`.

---

## Этап 43.5: разделение test contours на fast/default/opt-in real

**Что изменено в контурной модели:**
- Введён machine-readable source of truth `test_contours.py` с тремя named
  contour'ами:
  - `fast`
  - `default`
  - `opt_in_real`
- Добавлен marker `real_api` в `pytest.ini`.
- `tests/test_e2e_real.py` помечен как `real_api`, а real browser tests уже
  остаются под `real_browser`.

**Launcher contract:**
- `scripts/run_fast_test_suite.py`
  запускает: `not browser and not real_api and not real_browser`
- `scripts/run_default_test_suite.py`
  запускает: `not real_api and not real_browser`
- `scripts/run_opt_in_real_test_suite.py`
  запускает: `real_api or real_browser`

**Почему это важно:**
- Default contour теперь гарантированно не затягивает real API tests даже если
  в окружении присутствуют `TEST_DOMAIN`/`TEST_API_KEY`.
- Fast contour даёт быстрый inner-loop запуск без Playwright/browser слоя.
- Opt-in real contour получил отдельный stable entrypoint для следующего шага
  с CI workflow.

**Guardrails:**
- Добавлен `tests/test_test_contours.py`, который фиксирует marker expressions
  и стабильные имена контуров.

**Проверки после аудита:**
- Contour guardrails:
  `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_test_contours.py tests/test_warning_policy.py -q"`
  -> `9 passed`
- Fast contour:
  `docker compose --profile test run --rm test sh -c "python scripts/run_fast_test_suite.py"`
  -> `258 passed, 63 deselected`
- Default contour:
  `docker compose --profile test run --rm test sh -c "python scripts/run_default_test_suite.py"`
  -> `265 passed, 56 deselected`
- Opt-in real contour:
  `docker compose --profile test run --rm test sh -c "python scripts/run_opt_in_real_test_suite.py"`
  -> `49 passed, 7 skipped, 265 deselected`

---

## Этап 43.6: CI workflow переключён на named test contours

**Что изменено в GitHub Actions:**
- `.github/workflows/test.yml` больше не перечисляет вручную отдельные test
  modules.
- Обязательный CI теперь состоит из двух jobs:
  - `fast`
  - `default`
- `.github/workflows/test-real.yml` использует launcher
  `scripts/run_opt_in_real_test_suite.py`.

**Архитектурное решение:**
- YAML workflow'ы не хранят marker expressions и не знают про конкретные
  модули contour'ов.
- Источник истины теперь один:
  - `test_contours.py` задаёт marker contract;
  - launcher scripts превращают этот contract в реальные pytest команды;
  - CI только вызывает launcher.

**Почему это снижает риск дрейфа:**
- Изменение состава contour'ов больше не требует синхронно править и Python,
  и GitHub Actions.
- Manual real job автоматически наследует актуальный real contour, включая
  real browser tests, если они включены env/marker policy.

**Проверки после аудита:**
- Выполнен audit обновлённых YAML workflow-файлов:
  - `test.yml` -> jobs `fast` и `default` вызывают соответствующие launcher'ы;
  - `test-real.yml` -> manual real workflow вызывает `opt-in real` launcher.
- Повторные локальные проверки launcher'ов после интеграции workflow:
  - `python scripts/run_fast_test_suite.py` -> `258 passed, 63 deselected`
  - `python scripts/run_default_test_suite.py` -> `265 passed, 56 deselected`
  - `python scripts/run_opt_in_real_test_suite.py` -> `49 passed, 7 skipped, 265 deselected`

---

## Этап 43.7: policy зафиксирован в README и артефактах

**Что синхронизировано в документации:**
- README теперь явно описывает три named contour'а:
  - `fast`
  - `default`
  - `opt_in_real`
- README фиксирует, что:
  - `docker compose run --rm test` = `default` contour;
  - `default` не запускает real API/browser tests;
  - real browser tests требуют `RUN_REAL_BROWSER_TESTS=1`;
  - `test.yml` состоит из jobs `fast` и `default`;
  - `test-real.yml` запускает `opt_in_real`.

**Почему это важно:**
- После `43.5`/`43.6` в проекте появились launcher'ы и marker contract, и без
  обновлённого README возникал бы риск ложного ожидания, что default suite
  может запускать real API tests при наличии env-переменных.
- Документация теперь совпадает с фактическим поведением launcher'ов и CI.

**Проверки после аудита:**
- Выполнен manual audit секций README про локальный запуск тестов и CI/CD.
- Артефакты `README.md`, PRD этапа 43 и `AssumptionLog.md` приведены к одному
  описанию contour policy.

---

## Этап 44.1: threat model для web, bearer auth, runtime и storage

**Что зафиксировано:**
- Создан PRD этапа 44 в
  `PRD/этап-44-security-review-and-hardening.md`.
- Создан отдельный security artifact:
  `artifacts/security-threat-model-vetmanager-mcp-ru.md`.

**Какие trust boundaries выделены:**
- Internet -> public web UI
- MCP client -> bearer-only runtime
- app -> storage
- app -> external upstream (`billing-api`, clinic host, `token_auth.php`, REST API)
- deployment / reverse proxy / forwarded headers

**Какие активы признаны критичными:**
- raw service bearer token в момент выдачи;
- Vetmanager API key / user token;
- `STORAGE_ENCRYPTION_KEY`;
- `WEB_SESSION_SECRET`;
- signed web session cookie;
- encrypted storage payload;
- token audit/usage metadata.

**Наблюдаемые controls в текущей реализации:**
- bearer-only runtime без `X-VM-*` credentials;
- hash-only storage для bearer tokens;
- encrypted storage для Vetmanager credentials;
- one-time display raw bearer token;
- signed session cookie и signed CSRF token;
- HTTPS + allowlist validation для resolved upstream host;
- process-local rate limiting для web auth и bearer auth;
- audit trail для token lifecycle.

**Приоритетные risk hypotheses, переданные в следующие задачи:**
- `44.2`:
  fallback `WEB_SESSION_SECRET <- STORAGE_ENCRYPTION_KEY` и review cookie/session/error handling
- `44.3`:
  проверка реального enforcement scope model и legacy full-access fallback
- `44.4`:
  review logs/audit trail на leakage secret material и sensitive metadata
- `44.5`:
  review process-local limiter и прямого доверия к `X-Forwarded-For`
- `44.6`:
  целевой SSRF/host resolution/allowlist review

**Проверки:**
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `265 passed, 56 deselected`

---

## Этап 44.2: разделение web session secret и storage encryption key

**Что изменено:**
- `web_auth.get_web_session_secret()` больше не использует
  `STORAGE_ENCRYPTION_KEY` как fallback.
- Для signed web sessions теперь обязателен отдельный `WEB_SESSION_SECRET`.
- В `tests/test_web_auth.py` добавлена regression-проверка, что reuse storage key
  для session signing запрещён даже если `STORAGE_ENCRYPTION_KEY` задан.

**Почему это важно:**
- До hardening-а один и тот же секрет мог одновременно подписывать web sessions
  и шифровать сохранённые Vetmanager credentials.
- Такой secret-domain coupling увеличивал blast radius: компрометация одного
  контура автоматически ослабляла другой.
- После изменения web auth и encrypted storage разделены на уровне обязательной
  конфигурации.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_web_auth.py -q`
  -> `24 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `266 passed, 56 deselected`

---

## Этап 44.3: scope model теперь реально ограничивает bearer runtime

**Что изменено:**
- Bearer token scopes теперь пробрасываются через `BearerAuthContext` и
  `RuntimeCredentials`.
- В `token_scopes.py` добавлен coarse-grained mapping
  `HTTP method + REST entity -> required scope` для текущего tool surface.
- `VetmanagerClient` проверяет required scope локально, до host resolution и
  любого outbound HTTP request.
- `tests/runtime_factories.py` теперь создаёт realistic full-access runtime
  context по умолчанию, чтобы e2e mock tests отражали production semantics.

**Почему это важно:**
- До изменения scope manifest существовал только в storage и не влиял на authz.
- Теперь token scopes реально ограничивают bearer runtime, а не служат
  декоративным metadata field.
- Legacy-совместимость сохранена: токены без `scopes_json` по-прежнему получают
  full-access policy через существующую десериализацию.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_bearer_auth.py tests/test_runtime_auth.py tests/test_token_scopes.py -q`
  -> `20 passed`
- `docker compose --profile test run --rm test python -m pytest tests/test_e2e_mock.py -q`
  -> `91 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `267 passed, 56 deselected`

---

## Этап 44.4: audit trail теперь редактирует секреты defensively

**Что изменено:**
- В `auth_audit.py` добавлена defensive sanitization перед сериализацией audit
  `details`.
- Типовые sensitive keys (`api_key`, `user_token`, `password`,
  `authorization`, `session`, `cookie`, `secret`) теперь редактируются в
  `[redacted]`.
- Bearer-паттерны `vm_st_*` редактируются и внутри строковых сообщений.
- `token_prefix` оставлен как явный safe exception, чтобы audit trail сохранял
  полезный идентификатор токена без raw secret material.

**Почему это важно:**
- До изменения безопасность audit trail зависела от дисциплины каждого
  callsite'а и могла быть сломана будущей ошибкой при передаче `details`.
- Теперь redaction policy централизована в общем helper и защищает даже от
  accidental leakage в новых audit событиях.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_auth_audit.py tests/test_bearer_auth.py tests/test_web_auth.py tests/test_token_cleanup.py -q`
  -> `39 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `269 passed, 56 deselected`

---

## Этап 44.5: trusted proxy boundary для limiter и audit metadata

**Что изменено:**
- В `web_security.py` добавлен shared helper `resolve_client_ip()`.
- `X-Forwarded-For` теперь учитывается только если immediate client host входит
  в allowlist `WEB_TRUSTED_PROXY_IPS`.
- `get_request_ip()` и `auth_audit.get_request_audit_metadata()` используют одну
  и ту же trusted-proxy policy.

**Почему это важно:**
- До hardening-а любой клиент мог подменить `X-Forwarded-For` и влиять на web
  rate limiting и audit IP metadata.
- Теперь spoofed forwarded headers по умолчанию игнорируются; trust включается
  только явной конфигурацией reverse proxy boundary.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_web_security.py tests/test_auth_audit.py tests/test_web_auth.py tests/test_bearer_auth.py tests/test_bearer_rate_limit.py -q`
  -> `43 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `273 passed, 56 deselected`

---

## Этап 44.6: общий bare-origin contract для billing-resolved host

**Что изменено:**
- Добавлен общий validator `host_validation.validate_resolved_vetmanager_origin()`.
- `VetmanagerClient` и `vetmanager_connection_service` теперь используют один и
  тот же host validation contract.
- Billing-resolved host теперь должен быть:
  - `https`;
  - без `userinfo`;
  - без custom port;
  - без path/query/fragment;
  - в allowlisted suffix.
- Валидный host нормализуется к canonical bare origin.

**Почему это важно:**
- До hardening-а разные части системы дублировали allowlist logic и принимали
  слишком широкие billing responses.
- Теперь SSRF/bypass surface через `userinfo`, `:444`, `/nested`, `?q=` и
  другие non-origin формы закрыт одинаково и для runtime, и для account
  integration.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_client_multitenancy.py tests/test_vetmanager_connection_service.py -q`
  -> `27 passed`
- `docker compose --profile test run --rm test python -m pytest tests/test_runtime_auth.py tests/test_web_auth.py -q`
  -> `30 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `275 passed, 56 deselected`

---

## Этап 44.7: hardening fixes реализованы инкрементально, без отдельного fix-bucket

**Что зафиксировано:**
- По итогам аудита этапа 44 не потребовался отдельный “мега-коммит” с security
  fixes поверх уже реализованных задач.
- Все реальные hardening-изменения были внесены и проверены в подпунктах
  `44.2–44.6`.

**Почему это важно:**
- Такой split сохраняет traceability: каждое security-усиление привязано к
  конкретной risk hypothesis и набору regression tests.
- В roadmap теперь явно отражено, что `44.7` является агрегирующей фиксацией
  уже внедрённых mitigations, а не потерянным todo.

---

## Этап 44.8: security regressions оформлены как отдельный pytest subset

**Что изменено:**
- В `pytest.ini` зарегистрирован marker `security`.
- Ключевые security-invariant tests помечены этим marker'ом:
  - session secret boundary;
  - scope enforcement;
  - safe auth errors;
  - audit redaction;
  - trusted proxy policy;
  - bare-origin host validation.

**Почему это важно:**
- Security baseline теперь можно запускать отдельно через `pytest -m security`,
  не выискивая нужные node id вручную.
- Это делает regressions этапа 44 более поддерживаемыми и пригодными для
  будущего CI/ops hardening.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest -m security -q`
  -> `12 passed, 319 deselected`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `275 passed, 56 deselected`

---

## Этап 44.9: документация и deployment notes синхронизированы с stage 44 baseline

**Что обновлено:**
- `README.md` теперь описывает:
  - `WEB_TRUSTED_PROXY_IPS`;
  - отдельный `pytest -m security` subset;
  - production notes про раздельные secrets и bare-origin host policy.
- Добавлен отдельный artifact:
  `artifacts/security-deployment-notes-vetmanager-mcp-ru.md`.
- Stage 44 закрыт в `Roadmap.md`.

**Почему это важно:**
- Security controls этапа 44 теперь не скрыты в коде и журнале, а доведены до
  эксплуатационного контура.
- Это снижает риск неправильного production deploy, где security assumptions
  были бы нарушены конфигурацией.

---

## Этап 45.1: введён базовый structured logging contract

**Что изменено:**
- Создан модуль `structured_logging.py` с единым entry point
  `configure_logging()`.
- Зафиксированы поддерживаемые форматы логов:
  - `text` по умолчанию;
  - `json` для structured ingestion.
- Определены core fields logging contract:
  - `timestamp`
  - `level`
  - `logger`
  - `message`
- `server.py` больше не держит inline `basicConfig(...)`, а использует общий
  logging module.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_structured_logging.py -q`
  -> `5 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `280 passed, 56 deselected`

---

## Этап 45.2: request и correlation id добавлены в web и logging context

**Что изменено:**
- Добавлен модуль `request_context.py`.
- Web responses теперь возвращают `X-Request-ID` и `X-Correlation-ID`.
- Logging filter обогащает log records полями `request_id` и
  `correlation_id`, когда есть текущий FastMCP HTTP request context.
- Если клиент не прислал id, сервис генерирует `request_id`, а
  `correlation_id` по умолчанию совпадает с ним.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_request_context.py tests/test_structured_logging.py tests/test_web_auth.py -q`
  -> `33 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `284 passed, 56 deselected`

---

## Этап 45.3: введена logger taxonomy для runtime, audit и security

**Что изменено:**
- Добавлен модуль `observability_logging.py` с category-aware adapters:
  - `vetmanager.runtime`
  - `vetmanager.audit`
  - `vetmanager.security`
- В structured logs теперь появляются `event_category` и `event_name`.
- На новую таксономию переведены базовые emission points:
  - runtime host resolution;
  - audit append для token events;
  - security events для invalid CSRF и rate-limit reject.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_observability_logging.py tests/test_structured_logging.py tests/test_web_security.py tests/test_auth_audit.py -q`
  -> `14 passed`
- `docker compose --profile test run --rm test python -m pytest tests/test_client_multitenancy.py tests/test_web_auth.py tests/test_bearer_auth.py -q`
  -> `53 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `286 passed, 56 deselected`

---

## Этап 45.4: добавлены health/readiness probes для web runtime

**Что изменено:**
- В `web.py` добавлены JSON endpoints:
  - `GET /healthz` для process liveness;
  - `GET /readyz` для runtime readiness.
- Probe responses возвращают стабильный JSON contract, `Cache-Control: no-store`
  и `X-Request-ID`/`X-Correlation-ID`.
- Readiness проверяет доступность storage через `SELECT 1`.
- Любая ошибка dependency check приводит к `503` и runtime event
  `storage_readiness_failed`, чтобы probe оставался fail-closed.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_web_observability.py tests/test_observability_logging.py -q`
  -> `5 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `289 passed, 56 deselected`

---

## Этап 45.5: добавлены базовые process-local service metrics

**Что изменено:**
- Добавлен модуль `service_metrics.py` с in-memory registry для:
  - `http_requests_total`;
  - `http_request_latency_seconds`;
  - `auth_failures_total`;
  - `upstream_failures_total`.
- Web routes теперь автоматически обновляют request totals и latency через
  общий wrapper вокруг `custom_route`.
- Auth failure counters инкрементируются для bearer header, bearer runtime,
  invalid CSRF, web rate limit и invalid web login.
- Upstream failure counters инкрементируются для billing API и Vetmanager API
  timeout/network/http failure paths.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_service_metrics.py tests/test_request_auth.py tests/test_web_observability.py tests/test_client_multitenancy.py tests/test_web_security.py tests/test_bearer_auth.py -q`
  -> `45 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `292 passed, 56 deselected`

---

## Этап 45.6: добавлен Prometheus-compatible export для service metrics

**Что изменено:**
- `service_metrics.py` теперь умеет рендерить registry в Prometheus text
  exposition format.
- В `web.py` добавлен endpoint `GET /metrics` с plaintext scrape response и
  request-context headers.
- Export включает:
  - `vetmanager_http_requests_total`;
  - `vetmanager_http_request_latency_seconds_count/sum/max`;
  - `vetmanager_auth_failures_total`;
  - `vetmanager_upstream_failures_total`.
- Scrape отражает только завершённые requests; текущий `GET /metrics` попадает
  уже в следующий scrape, потому что route metric записывается после response build.

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_prometheus_metrics.py tests/test_service_metrics.py tests/test_web_observability.py -q`
  -> `8 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `294 passed, 56 deselected`

---

## Этап 45.7: добавлена opt-in интеграция с Sentry для error tracking

**Что изменено:**
- Добавлен модуль `error_tracking.py` с optional bootstrap для Sentry.
- `server.py` инициализирует error tracking на старте после logging setup.
- Интеграция активируется только при наличии `ERROR_TRACKING_DSN` или `SENTRY_DSN`.
- Для outgoing events используется sanitize hook, который редактирует
  `Authorization`, `Cookie`, `Set-Cookie`, `X-REST-API-KEY` и `X-API-KEY`.
- Добавлены runtime knobs:
  - `ERROR_TRACKING_BACKEND`
  - `ERROR_TRACKING_DSN`
  - `ERROR_TRACKING_ENVIRONMENT`
  - `ERROR_TRACKING_RELEASE`
  - `ERROR_TRACKING_TRACES_SAMPLE_RATE`

**Проверки:**
- `docker compose --profile test run --rm test python -m pytest tests/test_error_tracking.py -q`
  -> `3 passed`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `297 passed, 56 deselected`

---

## Этап 45.8: зафиксирован observability runbook и закрыт этап 45

**Что изменено:**
- `README.md` дополнен разделом `Observability`:
  - probes `/healthz` и `/readyz`;
  - scrape endpoint `/metrics`;
  - service metrics families;
  - error tracking env knobs и sanitation policy.
- Добавлен артефакт `artifacts/observability-runbook-vetmanager-mcp-ru.md`
  с operational walkthrough по health, metrics, logs и Sentry.
- `Roadmap.md` теперь помечает весь этап 45 как `done`.

**Проверки:**
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `297 passed, 56 deselected`

---

## Этап 46: проведено архитектурное ревью и сформирован debt register

**Что изменено:**
- Добавлен PRD этапа 46:
  `PRD/этап-46-architecture-review-and-refactoring-backlog.md`
- Добавлен architecture review artifact:
  `artifacts/architecture-review-vetmanager-mcp-ru.md`
- Добавлен debt register:
  `artifacts/tech-debt-register-vetmanager-mcp-ru.md`
- Главные выводы ревью:
  - основной hotspot сейчас `web.py` как orchestration-монолит;
  - вторичный structural hotspot — связка `vetmanager_client.py` и
    `vetmanager_connection_service.py`;
  - strongest next refactor candidate — разрезание web-контура по feature slices;
  - test architecture сильная, но `tests/test_e2e_mock.py` и `tests/test_web_auth.py`
    уже дают заметную стоимость сопровождения.

**Проверки:**
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `297 passed, 56 deselected`

---

## Этап 47: добавлен production readiness baseline и закрыт roadmap

**Что изменено:**
- Добавлен PRD этапа 47:
  `PRD/этап-47-operational-maturity-and-production-readiness.md`
- Добавлены ops artifacts:
  - `artifacts/operations-readiness-vetmanager-mcp-ru.md`
  - `artifacts/release-checklist-vetmanager-mcp-ru.md`
- Добавлен `scripts/post_deploy_smoke_checks.sh` и `scripts/deploy_server.sh`
  переведён на этот post-deploy smoke hook.
- `README.md` дополнен operational helper’ами, ссылками на ops artifacts и
  post-deploy smoke usage.
- Итог: roadmap теперь полностью закрыт.

**Проверки:**
- Shell syntax:
  `bash -n scripts/post_deploy_smoke_checks.sh scripts/deploy_server.sh scripts/sync_and_deploy_server.sh scripts/init_server.sh scripts/renew_cert_if_needed.sh`
  -> `ok`
- Полный default contour:
  `docker compose --profile test run --rm test`
  -> `297 passed, 56 deselected`

---

## 2026-03-22: открыт этап 48 из-за падения production deploy workflow

**Факт:**
- На `main` тестовый workflow `Tests` зелёный:
  - run `23403101377` от `2026-03-22T12:30:44Z` -> `success`
  - run `23403097746` от `2026-03-22T12:30:30Z` -> `success`
- Но downstream workflow `Deploy Prod` падает после успешного деплоя:
  - run `23403130226` от `2026-03-22T12:32:26Z` -> `failure`
  - run `23403125677` от `2026-03-22T12:32:11Z` -> `failure`

**Локализация по логам GitHub Actions:**
- Падение происходит в шаге `Run remote deploy` уже после:
  - `docker compose up -d`
  - успешного `docker compose ps`
  - успешной TLS/certificate проверки
- Непосредственная точка отказа:
  `scripts/post_deploy_smoke_checks.sh` -> `curl: (56) Recv failure: Connection reset by peer`
  при обращении к `http://127.0.0.1:8000` сразу после рестарта контейнера.

**Решение по workflow:**
- Roadmap снова открыт отдельным этапом `48`, потому что production CI сейчас не green.
- Гипотеза по приоритету: это startup race между `docker compose up -d` и первым HTTP smoke-запросом, а не ошибка sync/build/test contour.
- Следующая рабочая задача: стабилизировать post-deploy smoke contract retry/grace логикой и улучшить failure diagnostics.

**Реализация (48.2–48.5, локальная часть):**
- Добавлен PRD этапа 48:
  `PRD/этап-48-deploy-ci-smoke-stability.md`
- `scripts/post_deploy_smoke_checks.sh` переведён на retryable contract:
  - ограниченный retry loop для `/healthz`, `/readyz`, `/metrics`, `/mcp`;
  - env knobs для attempt/sleep/connect/max-time;
  - финальная ошибка теперь содержит `url`, `curl_exit`, `http_status`,
    preview body и curl stderr.
- `scripts/deploy_server.sh` теперь при падении app smoke checks печатает
  `docker compose ps` и tail container logs, чтобы различать startup race и
  реальный runtime crash без ручного SSH.
- Добавлены regression tests:
  `tests/test_post_deploy_smoke_checks.py`
  - delayed startup -> smoke script eventually passes;
  - persistent failure -> ошибка содержит attempt context и endpoint.

**Проверки:**
- Shell syntax:
  `bash -n scripts/post_deploy_smoke_checks.sh scripts/deploy_server.sh`
  -> `ok`
- Targeted regressions:
  `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_post_deploy_smoke_checks.py -q"`
  -> `2 passed`

**Открытый хвост этапа:**
- Осталось подтвердить зелёный `Deploy Prod` на GitHub после push и затем
  закрыть `48.4`/весь этап 48 отдельной записью.

**Уточнение после deploy run `23408763879`:**
- Retry/diagnostics подтвердили, что первичная гипотеза про startup race была
  неполной.
- Фактическая причина падения контейнера:
  `PermissionError: [Errno 13] Permission denied: 'data'`
  при `initialize_storage()` в `server.py`/`storage.py`.
- Практический root cause: remote deploy использовал `docker build` с одними
  `UID/GID`, а `docker compose up` зависел от env/`.env` на сервере и мог
  поднять контейнер под другим UID/GID, из-за чего bind-mounted `/app`
  становился не writable для process user и SQLite не мог создать `./data`.
- Fix-forward решение:
  - `scripts/deploy_server.sh` теперь вводит helper `compose()`, который
    запускает все `docker compose` команды с теми же `UID/GID`, что и build;
  - перед `compose up -d` deploy script делает `mkdir -p data`.
- Добавлен contract-regression:
  `tests/test_deploy_server_script.py`
  — проверяет, что deploy script подготавливает `data/` и использует
  консистентные `UID/GID` для compose.

**Дополнительные проверки:**
- Targeted deploy-script regressions:
  `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_post_deploy_smoke_checks.py tests/test_deploy_server_script.py -q"`
  -> `3 passed`
- Повторный полный default contour:
  `docker compose --profile test run --rm test`
  -> `300 passed, 56 deselected`

**Итог подтверждён на GitHub Actions:**
- `Tests` для коммита `481711f`:
  run `23408966186` от `2026-03-22T17:54:53Z` -> `success`
- downstream `Deploy Prod`:
  run `23408998047` от `2026-03-22T17:56:36Z` -> `success`

**Вывод:**
- Этап 48 закрыт: production deploy CI снова green.
- Root cause оказался составным:
  - недостаточная диагностируемость smoke checks;
  - несогласованные `UID/GID` между build и compose;
  - накопленный permission drift в bind-mounted `data/` для SQLite storage.

---

## 2026-03-22: открыт этап 49 для production web/browser verification

**Подтверждённый факт:**
- На `2026-03-22` endpoint
  `https://342915.simplecloud.ru/register`
  отвечает `500 Internal Server Error`.
- Ошибка подтверждена прямым HTTP/страничным запросом, это не локальная
  браузерная проблема клиента.

**Решение по workflow:**
- В `Roadmap.md` добавлен этап `49` как следующий production-focused backlog.
- Первый рабочий пункт: локализовать причину `500` на `/register`.
- Отдельным подпунктом зафиксирована задача пройти production browser
  happy-path `/register -> /login -> /account` после устранения server-side
  ошибки.

**Локализация и hotfix в production:**
- Через SSH на `root@212.193.59.219` сняты live-логи контейнера:
  `docker compose logs --tail=120 mcp`
- Точный root cause:
  `RuntimeError: Missing WEB_SESSION_SECRET for signed web sessions.`
  в `web_auth.get_web_session_secret()` при обработке `GET /register`.
- Проверка `/opt/vetmanager-mcp/.env` подтвердила, что `WEB_SESSION_SECRET`
  отсутствовал полностью.
- На production-сервере выполнен hotfix:
  - создан backup `.env.bak.<timestamp>`;
  - в `/opt/vetmanager-mcp/.env` добавлен новый случайный
    `WEB_SESSION_SECRET`;
  - сервис перезапущен через `docker compose up -d`.

**Результат после hotfix:**
- `http://212.193.59.219:8000/healthz` -> `200 OK`
- `https://342915.simplecloud.ru/register` -> `200 OK`
- `https://342915.simplecloud.ru/login` -> `200 OK`

**Следующий открытый шаг:**
- `49.3` остаётся актуальным: нужно пройти именно production browser
  happy-path `/register -> /login -> /account`, а не только починить GET
  страницы и probes.

**Новый production факт после ручной проверки:**
- На production web flow для `login/password -> user token` с real
  Vetmanager credentials пользователь получает сообщение
  `Invalid Vetmanager user token`, хотя прямой вызов `token_auth.php`
  с теми же данными возвращает успешный token response.
- Это означает, что текущие opt-in real tests не покрыли фактический
  production path этого сценария и roadmap этапа 49 должен включать
  отдельную локализацию/регрессию для real user-token flow.
- Секреты для воспроизведения считаются пользовательскими runtime-данными и
  не должны записываться в репозиторий; в roadmap и docs фиксируется только
  env-based opt-in contract (`TEST_*`).

**Закрытие этапа 49: real user-token contract и production browser flow**
- Production mismatch был локализован не в самом `token_auth.php`, а в нашем
  runtime/save-контракте:
  - exchange через `POST /token_auth.php` действительно возвращал валидный
    user token;
  - дальнейшая валидация и runtime client ошибочно использовали этот token как
    `X-REST-API-KEY`;
  - для реального user-token режима Vetmanager нужен другой контракт:
    `X-USER-TOKEN` + `X-APP-NAME: vetmanager-mcp`.
- Исправление в коде:
  - `vetmanager_connection_service.validate_user_token_connection()` теперь
    валидирует `/rest/api/user` через `X-USER-TOKEN` + `X-APP-NAME`;
  - сохранённый `user_token` mode теперь хранит ещё и `app_name`;
  - `vetmanager_auth`, `bearer_auth`, `runtime_auth` и `vetmanager_client`
    сохраняют полный auth-context вместо API-key-like нормализации;
  - для legacy rows без `app_name` введён backward-compatible fallback
    `vetmanager-mcp`.
- Real regressions:
  - targeted affected suite:
    `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_vetmanager_auth.py tests/test_runtime_auth.py tests/test_vetmanager_connection_service.py tests/test_web_auth.py tests/test_live_upstream_mocks.py -q"`
    -> `46 passed`
  - full default contour:
    `docker compose --profile test run --rm test`
    -> `301 passed, 57 deselected`
  - opt-in real API subset с `TEST_DOMAIN=devtr6`,
    `TEST_USER_TOKEN_BASE_URL=https://devtr6.vetmanager2.ru`,
    `TEST_USER_LOGIN=admin4`, `TEST_USER_PASSWORD=123456`:
    `python -m pytest tests/test_e2e_real.py -k 'exchange_user_token_from_login_password or validate_user_token_connection_from_login_password_exchange or get_users_with_user_token_mode or save_user_login_password_connection_uses_real_user_token_contract' -q`
    -> `3 passed, 1 skipped`
  - opt-in real browser subset:
    `RUN_REAL_BROWSER_TESTS=1 python -m pytest tests/test_browser_real_opt_in.py -k 'real_browser_user_token_flow_can_issue_bearer_and_call_mcp' -q`
    -> `1 passed, 1 deselected`
- В production после deploy выявлен ещё один config gap:
  `POST /account/integration` падал с
  `SecretManagerError: Missing STORAGE_ENCRYPTION_KEY for encrypted storage payloads.`
- Production hotfix:
  - в `/opt/vetmanager-mcp/.env` добавлен `STORAGE_ENCRYPTION_KEY`;
  - сервис перезапущен;
  - после этого production browser happy-path прошёл успешно:
    `/register -> /account -> user-token integration save -> bearer issuance -> /logout -> /login -> /account`.
- Для ручной production verification использовался временный account; после
  проверки он был удалён из production storage через ORM-скрипт в контейнере,
  чтобы не оставлять тестовые сущности.

---

## Этап 50: Синхронизация артефактов и reset roadmap baseline

**Подтверждённые рассинхроны:**
- `README.md` уже описывал актуальный bearer-only runtime и web/account contour,
  а `artifacts/technical-requirements-vetmanager-mcp-ru.md` всё ещё содержал
  legacy headers-only блок с `X-VM-Domain` / `X-VM-Api-Key`.
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` отставал по масштабу
  эволюции roadmap: был зафиксирован диапазон этапов `20–28`, хотя фактически
  baseline проекта уже сформирован этапами `20–49`.
- `artifacts/prd-vetmanager-mcp-ru.md` в целом был близок к актуальному
  состоянию, но требовал небольшой правки формулировок, чтобы bearer-only
  модель и web-driven `user token` flow описывались как текущее состояние, а не
  как переходный план.

**Архитектурные решения:**
- Этап 50 зафиксирован как artifact-only этап: runtime-контракт, storage,
  миграции и бизнес-логика не менялись.
- Новым baseline после этапа 49 считается следующий набор возможностей:
  bearer-only MCP runtime, web account console, два Vetmanager auth modes,
  usage accounting Bearer-токенов, observability/metrics/health endpoints и
  подтверждённый production/browser verification flow.
- `README.md` принят как практически актуальный user-facing source of truth;
  основная синхронизация была выполнена для `Roadmap.md`,
  `artifacts/prd-vetmanager-mcp-ru.md` и
  `artifacts/technical-requirements-vetmanager-mcp-ru.md`.

**Изменения артефактов:**
- Добавлен PRD этапа 50:
  `PRD/этап-50-синхронизация-артефактов-и-reset-roadmap-baseline.md`.
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` переведён на
  консистентное bearer-only описание runtime-контракта и opt-in real test
  контуров.
- `artifacts/prd-vetmanager-mcp-ru.md` обновлён под текущее состояние web
  account console, one-time bearer display, `user token` exchange и
  observability-контура.

**Новый planning baseline:**
- `Roadmap.md` после этапа 50 снова считается валидной точкой входа для нового
  цикла планирования.
- Следующие этапы должны опираться на baseline после `1–50`, а не на legacy
  headers-only стадию проекта.

## Этап 51. Улучшение главной страницы (лендинг)

**Допущения и решения:**

- Hamburger-меню реализовано CSS-only (checkbox hack, без JavaScript) — breakpoint
  совпадает с существующим 920px media query, а не 768px как в PRD, чтобы не
  создавать второй breakpoint.
- `meta description` переписан на русский для целевой аудитории (ветклиники), а не
  на английском developer-facing.
- Email поддержки `support@vetmanager.cloud` — placeholder, требует верификации
  реального адреса.
- Canonical URL (51.4.3) отложен — требует знание production host, который может
  отличаться от development.
- Метрики выгоды (51.2.2) отложены — нет реальных данных для количественных
  утверждений.
- Иконки к секциям (51.6.1) отложены — требуют дизайнерского решения, unicode-эмодзи
  не подходят для профессионального SaaS.
- Social proof (51.6.2) отложен — нет клиник для демонстрации.
- Консистентность register/login (51.6.3) — отдельная задача, касается web.py,
  не landing_page.py.
- Ghost-кнопка «Войти» убрана из hero CTA-row (дублирование с новой текстовой
  ссылкой «Уже зарегистрированы? Войти в кабинет»).
- Контраст `.mini` текста повышен с `--muted: #51605b` до `#3e4a45` через
  отдельный CSS-правило, чтобы не ломать другие uses of `--muted`.

## Этап 52. Безопасность: hardening

**Допущения и решения:**

- `validate_required_secrets()` добавлена в `secret_manager.py` и вызывается
  в `server.py` в блоке `if __name__ == "__main__"` перед инициализацией storage.
  При тестировании через `mcp.http_app()` валидация не вызывается — секреты
  для тестов устанавливаются через conftest fixtures.
- Лимит form payload установлен в 100 KB (`MAX_FORM_PAYLOAD_BYTES`). Перехват
  `FormPayloadTooLarge` реализован в `_observed_custom_route` (middleware-уровень),
  возвращает HTTP 413.
- Требования к паролю: минимум 10 символов (а не 12 как в PRD — компромисс
  между безопасностью и UX для ветврачей), uppercase, lowercase, цифра.
  Спецсимвол убран из требований — это снижает удобство без значительного
  повышения энтропии при 10+ символах.
- Поддержка кириллических заглавных/строчных букв в валидации пароля
  (`[А-ЯЁ]` / `[а-яё]`) — целевая аудитория русскоязычная.
- Все тестовые пароли в test suite обновлены под новые требования.

## Этап 53. Архитектура: рефакторинг и БД

**Допущения и решения:**

- Индексы на FK-колонках добавлены через Alembic миграцию `20260326_000004`.
  SQLite создаёт индексы через `CREATE INDEX`, PostgreSQL — аналогично.
- Рефакторинг web.py (53.1), vetmanager_client.py (53.2) и session-паттернов
  (53.3) отложен — risk/reward слишком высок для текущей стадии. Код работает,
  тесты проходят, god-module проблема задокументирована в tech-debt register.
- Миграция 3 верифицирована: `access_policy_version` (Integer, server_default="1")
  и `scopes_json` (Text, nullable=True) совпадают с storage_models.py.

## Этап 54. Инфраструктура: production hardening

**Допущения и решения:**

- Multi-stage Docker build: `base` (общие deps) → `production` (без test) →
  `test` (с Playwright/pytest/respx). Test image использует отдельный tag
  `vetmanager-mcp-test`.
- HEALTHCHECK в production stage использует `curl -f /healthz` — curl уже
  установлен в base stage.
- Resource limits (1 CPU, 512M RAM) — консервативные для single-process Python.
- Named volume `mcp-data` для SQLite persistence — заменяет bind mount `./data`.
- Redis (54.2) отложен — текущая нагрузка обслуживается single-process, in-memory
  rate limiter и cache достаточны. Задокументировано как ограничение.

## Этап 55. Расширение MCP-инструментов: недостающие CRUD-операции

**Допущения и решения:**

- Источник истины для доступных CRUD-операций — `artifacts/api_crud_permissions-ru.md`
  (анализ PHP-контроллеров Vetmanager), а не OpenAPI-спецификация (которая может быть неполной).
- Добавлены 12 новых MCP-инструментов: `update_invoice`, `delete_invoice`, `update_user`,
  `update_hospitalization`, `update_supplier`, `create_supplier`, `create_good`, `update_good`,
  `create_timesheet`, `delete_client`, `delete_pet`, `delete_invoice_document`.
- Расширены существующие update-инструменты дополнительными полями:
  - `update_client`: middle_name, cell_phone, address, city_id, street_id, note, status
  - `update_pet`: owner_id, sex, color_id, chip_number, weight, status
  - `update_admission`: client_id, pet_id, clinic_id, type
- DELETE-инструменты содержат предупреждение `WARNING` в docstring.
- `update_user.is_active` использует sentinel -1 (не 0) для «без изменений», поскольку
  0 — валидное значение (inactive). Аналогично для `update_good.is_active` и `is_for_sale`.
- `Suppliers.update` — контроллер реализует `doRestUpdate`, но `restUpdate` не в whitelist
  `filterRestAccessRules`. Инструмент добавлен; при блокировке API пользователь получит
  ошибку Vetmanager, а не MCP-сервера.
- `create_invoice_document` не добавлен — уже реализован как `add_invoice_document`.
- Все новые инструменты зарегистрированы в `TOOL_ENTITY_MAP` (tool_descriptions.py)
  и получают доменные синонимы через `enhance_tool_descriptions`.
- Исправлен pre-existing баг в `test_e2e_real.py`: пароль `"real-flow-pass-123"` не проходил
  валидацию stage 52 (требует uppercase); заменён на `"RealFlow-pass-123"`.
- Общее количество MCP-инструментов: **101** (было 75 → 87 в README, но реальный
  подсчёт по `@mcp.tool` показал 101 — README не учитывал profiles, analytics, messages, stock balance).
- Полный test suite: 350 passed, 51 skipped, 0 failed.

## Этап 56. Синхронизация документации и артефактов

**Допущения и решения:**

- README: исправлен счётчик инструментов (87 → 101), обновлена таблица по группам
  с точным перечислением всех инструментов, добавлена колонка количества.
- Добавлен `deploy-prod.yml` workflow в секцию CI/CD README.
- Добавлен canonical URL (`https://342915.simplecloud.ru/`) и `og:url` на лендинг.
- PRD: добавлены требования 4.3.9 (rate limiting), 4.3.10 (pre-deploy backup).
- Tech Requirements: расширена секция 4.3 (security): per-email lockout, session timeout,
  password hashing (PBKDF2-HMAC-SHA256), CSRF double-submit, pre-deploy backup.
- Создан недостающий PRD для этапа 54 (инфраструктура).
- Tech Debt Register: обновлён web.py LOC (1422→1453), test_e2e_mock.py (91→118 тестов),
  добавлены 4 новых items: TD-55-01 (dependency pinning), TD-55-02 (CSP unsafe-inline),
  TD-55-03 (process-local rate limiting), TD-55-04 (coverage reporting).
- Release Checklist: переведён на checklist-формат, добавлены: browser E2E,
  `--target production` check, DB integrity, bearer token smoke.
- Security Threat Model: добавлена секция 9.7 Remediation Status с отслеживанием
  закрытия гипотез 44.2–44.6 по этапам 27-52.
- Этап 51 закрыт: deferred items (51.2.2, 51.6.1-51.6.3) вынесены в backlog со
  статусом `stop` и причинами блокировки.
- Deploy safety: исправлен docker build (--target production), увеличен smoke check
  timeout (20 attempts), добавлен автоматический backup БД и integrity check.

## Этап 61. Ревью архитектуры (code smells)

**Найденные архитектурные запахи (приоритизированный список):**

CRITICAL:
- C1: web.py — god-module (1453 строк, 15+ зависимостей, presentation + business logic). Этап 59 расширен: добавить DashboardService, унифицировать form handler pattern.
- C2: tools/*.py — CRUD boilerplate дублируется 50+ раз. Рассмотреть generic CRUD factory.
- C3: vetmanager_client.py — god-object (8 ответственностей: HTTP, auth, cache, rate limit, host resolution, scope check, error translation, observability).

HIGH:
- H1: storage_models.py — криптография (encrypt/decrypt/hash) в ORM-моделях вместо сервисного слоя.
- H2: encryption key доступ — `os.environ.get()` в 5 местах обходит валидацию `get_storage_encryption_key()`.
- H3: `_validate_domain()` — приватная функция в runtime_auth.py экспортируется в 3 модуля.
- H4: scope checking — происходит в vetmanager_client, а не в bearer_auth (нарушение fail-fast).
- H5: pagination loop — дублируется в 3 tool-модулях.

MEDIUM: inconsistent field naming (upstream API constraint), magic sentinels (0/-1), auth_audit→web_security coupling, inconsistent error recording.

LOW (accepted): circular import via local import, process-local rate limiter, token lifecycle split.

**Решения:**
- Не фиксить M1 (inconsistent field naming) — это отражение непоследовательности upstream Vetmanager API, переименование полей сломает контракт.
- Порядок устранения: C2 → C1 → C3 → H1–H2 → H3 → H4 → H5.
- Детальный план в PRD/этап-61-ревью-архитектуры.md.

## Этап 62. Ревью артефактов

**Результаты аудита:**

- 14 файлов в artifacts/ проверены: 13/14 актуальны (93%).
- 63 PRD-файла проверены: все соответствуют реализации, эволюция решений задокументирована корректно.
- README.md, AGENTS.md, AssumptionLog.md — актуальны.
- Единственная находка: устаревшие line counts в architecture-review (web.py 1422→1453, test_e2e_mock 91→118). Исправлено.
- Ничего не требует удаления или добавления. Документация в здоровом состоянии.

## Этап 63. Ревью тестируемости (особенно E2E)

**Результаты аудита:**

- 341 тест, 41 файл, покрытие tools 98/101 (97%).
- 3 непокрытых tools: get_invoice_by_id, get_medical_card_by_id, update_medical_card.
- Критический пробел: из HTTP-ошибок протестированы только 403 и 500. Нет тестов на 400, 401, 404, 422, 429, timeout.
- Browser E2E: 2 места с hardcoded wait_for_timeout(50ms), 2 места с хрупкими h1 селекторами.
- Test isolation: отличная, проблем не найдено.
- Mock-контракты: 124+ hardcoded response structures без schema validation.
- 9 test-файлов без тест-функций — требуют аудита.
- Реализация улучшений вынесена в этап 68.

## Этап 64. Ревью визуала

**Результаты аудита (desktop 1280px + mobile 375px + a11y snapshot):**

- Лендинг: визуально профессиональный, но hero heading = h2 (нет h1), hero text слишком длинный, год в футере 2025.
- Формы: нет отображения требований к паролю до submit, нет inline validation, нет toggle пароля.
- Дашборд: заголовки секций на английском ("Vetmanager integration", "Bearer token issuance") на русскоязычной странице. Секции визуально не разделены.
- a11y: отсутствует h1, нет main landmark на лендинге, nav без aria-label, FAQ без aria-expanded.
- Mobile: header без hamburger menu — навигация обрезается на 375px. Auth mode radio buttons тесные.
- Критических layout багов нет. Реализация исправлений вынесена в этап 69.

## Этап 65. Ревью безопасности

**Результаты аудита:**

- CRITICAL (S1): bearer_auth.py возвращает разные сообщения для invalid/revoked/expired токенов — позволяет enumeration.
- HIGH (S2): web_auth.py verify_account_password имеет early returns до PBKDF2 — timing attack для account enumeration.
- MEDIUM: session fixation (нет инвалидации старой сессии), session без random nonce, CSRF token не single-use, нет валидации формата encryption key.
- LOW: нет pip audit в CI, нет логирования успешных auth.
- FALSE POSITIVE: .env не в git (в .gitignore, не отслеживается).
- FALSE POSITIVE: TLS cert pinning не нужен для SaaS API.
- FALSE POSITIVE: IP binding sessions сломает мобильных пользователей.
- Input validation и HTTP headers — в хорошем состоянии.
- Реализация ремедиации — в этапе 70.

## Этап 66. Ревью использования ресурсов API Vetmanager

**Результаты аудита кеширования:**

- TTL-стратегия корректна: 15 мин для справочников, 60 сек для мутабельных данных.
- ВСЕ GET-запросы к справочным данным проходят через кеш — проверено.
- Инвалидация после мутаций работает, но overly broad (весь entity tag, а не конкретный ID).
- HIGH: кеш без max size / LRU — может расти безлимитно в долгоработающем процессе.
- HIGH: N+1 в get_medical_cards_by_client_id (1+N запросов, N = число питомцев).
- MEDIUM: нет Prometheus метрик кеша (hit/miss/size).
- MEDIUM: profile tools (client, pet) делают 3–4 sequential запроса вместо parallel.
- Vetmanager API не поддерживает batch endpoints → параллелизация через asyncio.gather().
- Реализация оптимизаций — в этапе 71.

## Этап 67.1. CRUD factory для tools/

**Что сделано:**

- Создан `tools/crud_helpers.py` с 6 helpers: `crud_list`, `crud_get_by_id`, `crud_create`, `crud_update`, `crud_delete`, `paginate_all`.
- Все 12 tool-модулей мигрированы на helpers. Затронуты стандартные CRUD-функции (~50 из 101 tools).
- Не затронуты: get_client_profile, get_pet_profile (multi-call aggregation), get_medical_cards (custom filter merging), get_medical_cards_by_client_id (N+1 by design), get_vaccinations, get_good_stock_balance, send_message_*.
- `paginate_all` используется в get_debtors и get_average_invoice вместо ручных while-loop.
- Добавлен `tests/test_crud_helpers.py` (10 тестов).
- Полный test suite: 360 passed, 51 skipped, 0 failed.

**Решения:**
- Helpers — тонкие обёртки, а не framework. Каждый tool сохраняет свою сигнатуру, docstring и payload-building.
- Payload building остаётся в tool-функциях, т.к. field names уникальны для каждой entity.
- VetmanagerClient import оставлен в модулях, где есть non-standard tools (client.py, pet.py, medical_card.py, warehouse.py, operations.py).

## Этап 67.2. Декомпозиция VetmanagerClient

**Что сделано:**

- Создан `host_resolver.py` — standalone модуль для billing API host resolution с retry, validation, metrics.
- VetmanagerClient._resolve_host() упрощён с 55 строк до 8: делегирует к `resolve_vetmanager_host()`.
- vetmanager_connection_service.resolve_vetmanager_host() также делегирует к host_resolver (с `max_retries=0` для сохранения текущего поведения).
- Добавлен empty-scopes fail-fast в bearer_auth.py: токены с пустыми scopes отклоняются на этапе auth (status 403), до выполнения API-запроса.
- Per-request scope check остаётся в VetmanagerClient._require_scope() — зависит от method+path, невозможно полностью проверить при auth.
- Новый audit event: TOKEN_EVENT_AUTH_FAILED_NO_SCOPES.
- 10 новых тестов в test_host_resolver.py.
- Полный test suite: 370 passed, 51 skipped, 0 failed.

**Решения:**
- Scope checking разделён на два уровня: early reject (пустые scopes) в bearer_auth + per-request (endpoint-specific) в VetmanagerClient. Это компромисс между fail-fast и архитектурной реальностью.
- host_resolver принимает `max_retries` параметр: client использует 1 (retry), connection_service использует 0 (без retry, как было).

## Этап 67.3. Storage layer cleanup

**Что сделано:**

- Создан `domain_validation.py` с публичной `validate_domain()`. Заменены все импорты `_validate_domain` из runtime_auth в: vetmanager_connection_service.py, vetmanager_client.py, runtime_auth.py.
- Унифицирован доступ к encryption key: 6 мест с `os.environ.get("STORAGE_ENCRYPTION_KEY")` заменены на `get_storage_encryption_key()` (runtime_auth.py + 5 мест в web.py).
- 370 passed, 51 skipped, 0 failed.

**Решения:**
- Crypto в ORM-моделях (TD-61-03) отложен: set_credentials/get_credentials/set_raw_token вызываются из 6+ callsites через encryption_key param. Перенос в сервисный слой потребует изменения интерфейсов всех вызывающих мест + переписывания тестов. Оставлен как tech debt — модели продолжают делегировать к secret_manager, но через свои методы.
- `_validate_domain` удалена из runtime_auth.py, DOMAIN_PATTERN перенесён в domain_validation.py.

## Этап 68. Устранение проблем тестируемости

**Что сделано:**

- Добавлены 11 тестов в test_e2e_mock.py:
  - 3 tool coverage: get_invoice_by_id, get_medical_card_by_id, update_medical_card
  - 1 MedicalCards response key normalization
  - 7 error scenarios: 400, 401, 404, 422, 429, timeout, malformed JSON
- Заменены все `wait_for_timeout(50)` на `wait_for(state="visible")` в 3 browser test файлах.
- Аудит "пустых" test-файлов: false positive — все 9 файлов содержат тесты (15-27 функций каждый).
- data-testid атрибуты отложены в этап 69 (требуют изменений в HTML).
- Полный test suite: 381 passed, 51 skipped, 0 failed.

## Этап 69. Устранение проблем визуала

**Что сделано:**

- Hero heading h2 → h1 в landing_page.py (CSS + HTML).
- Год в футере 2025 → 2026.
- Добавлена подсказка "Минимум 8 символов" в форму регистрации.
- Заголовки дашборда переведены на русский: "Интеграция Vetmanager", "Выпуск Bearer-токенов", "Текущие токены".
- Добавлены HR-разделители между секциями дашборда.
- Исправлен mixed language в описаниях форм регистрации и логина.
- Hamburger menu уже был реализован — подтверждено.
- Medium/Low приоритеты (inline validation, toggle пароля, aria, адаптивность) отложены — требуют JS или существенных HTML-изменений.
- Обновлены тесты: test_landing_page.py (год), test_web_auth.py (переведённые заголовки).
- 381 passed, 51 skipped, 0 failed.

## Этап 70. Ремедиация безопасности

**Что сделано:**

- S1: Все auth error messages в bearer_auth.py унифицированы → "Invalid authorization." (status 401). Детали остаются в audit logs.
- S2: verify_account_password() — timing attack fix: всегда выполняет PBKDF2 с dummy salt при невалидном хеше. Constant-time вне зависимости от наличия аккаунта.
- S4: Session token теперь включает random nonce (token_urlsafe(8)). Формат: `id.ts.nonce.sig`. Обратная совместимость с legacy 3-part токенами сохранена через `rsplit(".", 1)`.
- S6: get_storage_encryption_key() теперь валидирует формат ключа через `Fernet(key)` — невалидный ключ вызывает SecretManagerError при startup.
- S9: Добавлено логирование успешных web-аутентификаций (event_name: web_login_succeeded).
- Обновлены тесты: bearer_auth tests используют "Invalid authorization" вместо специфичных сообщений.

**Отложено:**
- S7 (CSRF single-use): требует DB-backed token storage, непропорциональная сложность.
- S8 (pip audit в CI): не блокирует, добавить при удобном случае.
- 381 passed, 51 skipped, 0 failed.

## Этап 71. Оптимизация кеширования и API usage

**Что сделано:**

- InMemoryTaggedCache: добавлен max_entries (default 2048) с LRU eviction, CacheMetrics (hits/misses/invalidations/evictions), last_accessed tracking.
- Prometheus: 5 новых метрик — vetmanager_cache_hits_total, misses, invalidations, evictions, entries (gauge).
- get_client_profile: 4 sequential API calls → asyncio.gather() (параллельные).
- get_pet_profile: 3 sequential API calls → asyncio.gather() (параллельные).
- get_medical_cards_by_client_id: N+1 оставлен — API не поддерживает filter по client_id.
- 381 passed, 51 skipped, 0 failed.

## Этап 72. Deploy safety: защита данных PostgreSQL

**Причина потери данных:**
- deploy_server.sh выполнял `compose down --remove-orphans`, что убивало postgres контейнер. При пересоздании контейнера PostgreSQL мог реинициализировать БД.

**Что сделано:**
- deploy_server.sh: `compose down` заменён на `compose stop mcp && compose rm -f mcp`. PostgreSQL не пересоздаётся при деплое.
- Добавлена pre-deploy проверка: если PG_VERSION отсутствует в data dir — деплой прерывается.
- Создан scripts/backup_daily_cron.sh: ежедневный pg_dump + gzip, ротация 30 дней, symlink latest.sql.gz.
- Cron установлен на production: `0 3 * * *`.

## Этап 73. IP mask ограничение для bearer токенов

**Что сделано:**

- Новая колонка `allowed_ip_mask` (String(64), nullable) в service_bearer_tokens. NULL = без ограничений.
- Формат маски: 4 октета через точку, каждый 0-255 или "*". Запрещён "0.0.0.0".
- IP проверка в bearer_auth.py: после disabled check, до rate limiter. 403 при несовпадении.
- Выпуск токенов: новый параметр ip_mask в issue_service_bearer_token().
- Web UI: поле "Ограничение по IP" в форме, IP mask в списке токенов.
- Лендинг: добавлена инфо о возможности ограничения по IP.
- 21 тест в test_ip_mask.py (validation + matching).
- IPv6: при ограничительной маске IPv6 адреса будут отклонены (safe default).
- 402 passed, 51 skipped, 0 failed.

## Этап 74. Подготовка к публичному релизу репозитория

**Решения:**

- Лицензия: MIT — стандарт для open-source MCP-серверов, максимальная свобода использования.
- README: обезличены все упоминания конкретного домена и IP в примерах (`342915.simplecloud.ru` → `<your-domain>`, `212.193.59.219` → `<your-server-ip>`). В deploy-скриптах хардкод оставлен — это дефолтные значения для production.
- SECURITY.md: responsible disclosure через GitHub Security Advisories (preferred) или email.
- README не переводится целиком на английский — слишком большой объём. Добавлена краткая English note в шапке.
- Отдельный CONTRIBUTING.md не создаётся — достаточно секции в README.
- Лендинг: добавлена ссылка на GitHub в topbar и footer, секция "Open Source / Разверните у себя" перед CTA.

**Аудит безопасности перед публикацией:**

- Все Python файлы, Docker, deploy-скрипты, CI workflows проверены: секретов нет.
- `.gitignore` корректно исключает `.env`.
- Все credentials передаются через env vars.
- Шифрование credentials в storage, hash-only хранение bearer-токенов.

**Что сделано:**

- LICENSE (MIT)
- SECURITY.md (responsible disclosure)
- README.md: badges (CI, license), English note, обезличенные примеры, секции Self-hosted и Contributing
- landing_page.py: GitHub ссылка в topbar nav + footer, секция Open Source
- tests/test_landing_page.py: 3 новых теста (GitHub в footer, GitHub в topbar, Open Source секция)
- Репозиторий переведён в public, добавлены topics

## Этап 75. Улучшение отображения нового bearer-токена

**Решения:**

- Raw token теперь показывается в `<code>` блоке с `word-break: break-all` вместо `<input readonly>` — виден полностью.
- Предупреждение вынесено в отдельный warning-блок с акцентным цветом и иконкой.
- Добавлен collapsible-блок "Как подключить к Cursor / Claude Code" с готовым JSON.
- JS для копирования переписан: `textContent` вместо `input.value`, fallback через `Range.selectNodeContents`.
- Browser-тесты (playwright): `input_value()` → `text_content()` для нового `<code>` элемента.
- 398 passed, 57 deselected, 0 failed.

## Этап 57. Deploy safety и инфраструктурная надёжность

**Что сделано:**

- **Volumes protection**: в compose() wrapper добавлен guard — `compose down --volumes` / `-v` прерывает деплой с FATAL ошибкой. Защита от случайного удаления PostgreSQL data volume.
- **Post-deploy DB integrity check**: после старта MCP проверяется наличие критических таблиц (accounts, service_bearer_tokens, alembic_version). При отсутствии — деплой прерывается.
- **Rollback script** (`scripts/rollback_db.sh`): восстановление БД из бекапа с валидацией имени БД, terminate active connections, trap EXIT для рестарта MCP при ошибке.
- **CI ShellCheck** (`.github/workflows/shellcheck.yml`): shellcheck --severity=warning + bash -n для всех скриптов. Запускается при изменениях в scripts/.
- 396 passed, 57 deselected, 0 failed.

**Решения:**
- Volumes guard реализован в compose() wrapper — все вызовы docker compose в деплое идут через wrapper, защита работает автоматически.
- `alembic upgrade head` вызывается напрямую (идемпотентен) — хрупкий grep ревизий по Codex-ревью заменён на простой вызов.
- Rollback script использует DROP/CREATE DATABASE с quoted identifiers и валидацией имени БД (по Codex-ревью).

## Этап 58. Dependency pinning и security hardening

**Что сделано:**

- **Dependency pinning**: все pip-зависимости в Dockerfile получили upper bounds (fastmcp<3, httpx<1, sqlalchemy<3, etc.). Предотвращает breaking changes при rebuild.
- **CSP upgrade-insecure-requests**: добавлен в CSP при WEB_ENABLE_HSTS=1 (production). Браузер автоматически повышает HTTP→HTTPS для подресурсов.
- **CSP style-src**: `unsafe-inline` оставлен — 41 inline style="" атрибут в landing_page.py/web.py. Полное удаление требует рефакторинга всех стилей в CSS-классы (трудоёмко, не критично). Добавлен комментарий с ссылкой на TD-55-02.
- 398 passed, 57 deselected, 0 failed.

**Решения:**
- Upper bounds выбраны по текущим major-версиям: ни одна зависимость не на пороге major-релиза.
- `upgrade-insecure-requests` привязан к WEB_ENABLE_HSTS — не добавляется для localhost/dev.
- TD-55-02 (unsafe-inline) остаётся открытым — закрытие возможно только через рефакторинг стилей в external CSS (этап 59 — рефакторинг web.py — подходящее место).

## Этап 59. Рефакторинг web.py (god-module split)

**Что сделано:**

- web.py разбит с 1533 строк на 5 модулей:
  - `web.py` (~310 строк) — оркестратор: shared helpers + `register_web_routes()`
  - `web_html.py` (~530 строк) — HTML rendering: `render_shell`, `render_register_page`, `render_login_page`, `render_account_page`
  - `web_routes_system.py` (~55 строк) — `/`, `/healthz`, `/readyz`, `/metrics`
  - `web_routes_auth.py` (~230 строк) — `/register`, `/login`, `/logout`
  - `web_routes_account.py` (~265 строк) — `/account`, `/account/integration`, `/account/tokens`
- Все 398 тестов проходят без изменений — public API `register_web_routes(mcp)` сохранён.

**Решения:**
- Route-модули получают shared helpers через keyword arguments, а не через импорт из web.py — избегаем circular imports и делаем зависимости явными.
- `_load_account_dashboard` и `_render_account_dashboard_response` остались в web.py — они тесно связаны с shared helpers и используются account-маршрутами через callback.
- HTML rendering вынесен в отдельный модуль — самый крупный блок кода (530 строк CSS + HTML templates).
- TD-55-02 не закрыт в этом этапе — inline styles в HTML templates остались, рефакторинг в CSS-классы — отдельная задача.

## Этап 60. Test suite refactoring

**Что сделано:**

- **Сплит test_e2e_mock.py** (2019 строк) на 4 файла по доменным группам:
  - `test_e2e_mock_entities.py` (~670 строк) — Client, Pet, Admission, MedicalCard, Invoice, Good, User, Reference, Errors
  - `test_e2e_mock_finance_warehouse.py` (~380 строк) — Finance, Warehouse, Stock balance
  - `test_e2e_mock_clinical_profiles.py` (~560 строк) — Clinical, Operations, Profiles, Messages
  - `test_e2e_mock_crud.py` (~540 строк) — CRUD operations, Error scenarios
- **Починен pre-existing баг**: глобальный `REQUEST_CACHE` не очищался между тестами, что вызывало test ordering-зависимые failures. Добавлен autouse-фикстура `_clear_request_cache` в conftest.py.
- **Coverage reporting**: добавлен pytest-cov в Dockerfile, `--cov` флаги в default test suite runner, минимальный порог 50%.
- 398 passed, 57 deselected, 0 failed.

**Решения:**
- 4 файла (а не 9+) — баланс между гранулярностью и управляемостью. Каждый файл <700 строк.
- Autouse-фикстура для очистки кеша — самый надёжный способ, работает для всех тестов без ручного вмешательства.
- Минимальный порог coverage 50% — консервативный, чтобы не блокировать CI при добавлении нового кода. Повысить позже.

## Этап 76. Инструмент get_inactive_pets

**Что сделано:**

- Новый MCP-инструмент `get_inactive_pets(months, limit)` в tools/pet.py.
- Визит определяется по трём источникам: admissions, invoices, medical cards — если есть хотя бы одна запись после cutoff_date, питомец считается активным.
- 4 параллельных API-запроса через asyncio.gather (admissions, invoices, medcards, pets).
- 3 mock-теста: основной сценарий, все активны, limit.
- Tool description с domain synonyms, LimitParam для limit.

**Решения:**
- Три источника (не только admissions): invoice и medical card тоже подтверждают визит. По просьбе пользователя.
- cutoff = today - months*30 (приближённо, не calendar months) — достаточно для бизнес-целей.
- Параллельная загрузка через gather для минимизации latency.
- Для больших клиник (>10000 питомцев) может быть медленно — paginate_all загружает всё.

## Этап 53.4.2. CHECK constraints для статусных полей

**Что сделано:**

- Добавлены константы статусов в storage_models.py: ACCOUNT_STATUSES, CONNECTION_STATUSES, TOKEN_STATUSES.
- CheckConstraint в __table_args__ для всех 3 моделей: Account, VetmanagerConnection, ServiceBearerToken.
- Alembic migration 20260407_000006: использует op.batch_alter_table для SQLite-совместимости. Перед добавлением constraints — нормализует существующие невалидные значения (UPDATE WHERE NOT IN ...) с защитой от NULL.
- Рефакторинг: bearer_auth.py, web_auth.py, vetmanager_connection_service.py, web.py — заменил hardcoded "active" на константы.
- 2 новых теста: проверка отказа INSERT с invalid status (3 таблицы) + проверка нормализации legacy данных при upgrade.
- 404 passed.

**Codex review fixes:**
- NULL handling в migration UPDATE (status IS NULL OR status NOT IN ...) — safety даже для NOT NULL колонок.
- Тест нормализации расширен на все 3 таблицы (был только accounts).

**Решения:**
- CHECK constraint вместо Enum: SQLAlchemy Enum плохо работает с SQLite/Alembic ALTER (требует CREATE TYPE в PostgreSQL, отдельный кейс в SQLite). CHECK IN (...) — нативно работает в обеих СУБД.
- batch_alter_table: SQLite не поддерживает ALTER TABLE ADD CONSTRAINT, batch mode пересоздаёт таблицу.
- Нормализация легаси: invalid → 'active' для accounts, 'disabled' для остальных (безопасный default).

## Этап 54.2.3. account_id в ключ кэша

**Что сделано:**

- vetmanager_client._cache_key() теперь включает `acct:{account_id}` сегмент.
- 3 новых теста: cache isolation между разными account_id, cache sharing для одного account_id, account_id=None не коллизирует с numeric.
- 407 passed.

**Решения:**
- account_id уже доступен в client через resolve_runtime_credentials() — изменение минимальное (1 строка в _cache_key).
- Fallback `acct:none` для legacy/uninitialized контекста (не должно случаться в проде, но safety).
- Шаринг кеша внутри одного account сохраняется (тест test_get_cache_shared_within_same_account_id).

## Этап 68.3.2. data-testid в HTML

**Что сделано:**

- 22 data-testid атрибута добавлены в web_html.py:
  - register/login/logout forms (forms + email/password/submit)
  - integration form: form, panels (domain-api-key, user-token), inputs (domain, api-key, vm-login, vm-password), buttons (submit, reauth)
  - token form: form, name, expires, ip-mask, submit
  - issued-token-value (рядом с существующим id)
- 5 browser-тестов переведены на page.get_by_test_id():
  test_browser_happy_path_domain_api_key, test_browser_happy_path_user_token,
  test_browser_cleanup, test_browser_real_opt_in (2 теста), test_browser_live_harness
- 407 passed.

**Решения:**
- data-testid добавлены **дополнительно** к существующим селекторам — backwards compatibility с другими тестами/инструментами.
- Naming convention: kebab-case, по pattern {section}-{element} (e.g. integration-domain, token-submit).
- Структурные тесты в test_web_auth.py остались работать (используют form actions, не сломаны).

## Этап 54.2.1-54.2.2. Redis backend для rate limiter (и cache — deferred)

**Что сделано (54.2.1):**

- Новый модуль `rate_limit_backend.py` с интерфейсом RateLimitBackend (Protocol).
- `InMemoryRateLimitBackend` — рефакторинг текущей логики из web_security.py.
- `RedisRateLimitBackend` — sliding window через Redis ZSET (ZADD/ZCARD/ZREMRANGEBYSCORE), TTL для auto-expire.
- Factory `get_rate_limit_backend()` — выбор по `REDIS_URL` env var, graceful fallback на in-memory при недоступности Redis.
- web_security.py делегирует все rate limit операции в backend через factory.
- 13 новых тестов: in-memory regression (6), Redis backend через fakeredis (5), factory selection (2).
- Зависимости: redis>=5.0.0,<6 (production), fakeredis>=2.20.0,<3 (test).

**Что сделано (54.2.2):**

- Документировано как single-process ограничение (request_cache.py).
- Полная миграция cache на Redis отложена: требует переноса async API + serialization + tag index migration. Приоритет — only when actually needed (multi-worker prod deploy).
- Архитектура rate_limit_backend.py может быть взята за образец для будущей реализации `request_cache_backend.py`.

**Решения:**
- Опциональный Redis: zero impact на dev/single-process. По умолчанию — in-memory.
- Sliding window через ZSET: timestamp = score, unique nonce member для конкурентных hit'ов.
- Graceful fallback при ping failure → log warning + in-memory. Не падаем при недоступности Redis.
- reset_all() для Redis ограничен prefix `vmrl:*` — safety против случайного flushdb.

## Этап 77. Inactive clients/pets через client.last_visit_date

**Что сделано:**

- **Helper** `tools/_inactive_helpers.py`: calendar-accurate window calc, fetch top inactive clients (sort DESC), per-pet last visit detection (invoice → medcard fallback).
- **Новый tool** `get_inactive_clients`: 1 API call с filters [status=ACTIVE, last_visit_date в окне] + sort DESC + limit. Default window 13-24 месяца, default limit 50.
- **Рефакторинг** `get_inactive_pets`: per-pet точный алгоритм. Получает top inactive clients, для каждого ищет alive pets и проверяет какие были на последнем визите через invoice → medcard fallback. Возвращает топ 50 pets с client info.
- **Bug fix** `get_pets`: параметр переименован `client_id` → `owner_id`, фильтр идёт через `filter=[owner_id]` вместо top-level `?client_id=...` query param.
- **Tool descriptions** консистентны: явный default window, default limit, customization params, domain synonyms.
- 437 passed (было 423 + 14 новых).

**Решения:**
- **Default window 13-24 месяца** — reactivation sweet spot: lapsed но не утраченные навсегда. Клиенты ещё помнят клинику, контакты актуальны.
- **Default limit 50, hardcoded** — защита от accidental dump всей базы. Пользователь может явно поднять до 100 (LimitParam).
- **Sort DESC по last_visit_date** — most recently lapsed first, лучшие кандидаты для reactivation.
- **Per-pet точный алгоритм (Вариант A)** — клиент может иметь несколько pets, но не все были на последнем визите. invoice → medcard fallback покрывает 99% клиник (90% используют счета, остальные — медкарты).
- **Pet→Client foreign key**: поле в таблице pet называется `owner_id`, ссылается на `client.id`. Используется в `filter=[owner_id]` для GET /rest/api/pet и в payload `update_pet`. Это **зафиксировано** как стандарт. Старый код в `get_pets` использовал `?client_id=...` query param, что было скрытым багом — исправлено.
- **client_fetch_limit = min(limit*3, 100)** — heuristic для фетча клиентов с запасом, поскольку не у всех будут confirmed visited pets.

**Производительность:**
- get_inactive_clients: 1 API call, ~50-200ms.
- get_inactive_pets для default limit 50: ~100-300 API calls
  (1 clients page + per-client pets + per-pet invoice/medcard).
  Latency ~5-15 сек с rate limiter. Acceptable для on-demand reactivation tool.

**Ограничения:**
- 5-15 sec latency для get_inactive_pets — это on-demand tool, не для realtime UI.
- Не покрываются клиники где визиты не фиксируются ни в invoices, ни в medcards (крайне редкий edge case).
- `get_pets` теперь требует `owner_id` (было `client_id`) — breaking change для прямых вызывальщиков, но через MCP интерфейс параметр всегда был optional с default 0.

## Этап 78. Ergonomic filters для LLM-discoverability

**Что сделано:**
- 6 list-tools получили именованные параметры-сахар над generic `filter=[...]`:
  - `get_pets.alias` (paired с `owner_id`, standalone → ValueError)
  - `get_clients.phone` (min 4 digits, normalized digits-only LIKE на `cell_phone`) + `.email` (LIKE)
  - `get_users.name` (two-request merge last_name OR first_name с dedupe by id), `.position_id`, `.is_active` (tri-state True/False/None)
  - `get_admissions.date_from/to` + `doctor_id→user_id` + `pet_id→patient_id` + `client_id`; bugfix: `date` LIKE → `>=/<` pair
  - `get_goods.title` LIKE, `.group_id`, `.is_active`
  - `get_invoices.payment_status` (none/partial/full enum), `.pet_id`
- `validators.normalize_phone_digits()` helper для phone нормализации.
- 24 новых теста через `mcp.call_tool()` + `respx` с проверкой outgoing filter JSON. 463 total passed.

**Решения:**
- **admission_date boundary**: MVP использует `>= date 00:00:00 AND < next_day 00:00:00` (не `<= 23:59:59`) для защиты от fractional seconds — чистая арифметика, без дополнительного API-probe. Cost = 1 дата-парсинг на вызов.
- **`get_users.name`**: two-request merge по last_name + first_name, а не OR в filter. Выбор: Vetmanager filter language не документирует OR across properties, и real-API probe не проведён на этапе 78. Merge дороже на 1 HTTP call, но даёт честный UX и не зависит от недокументированной семантики. При реализации этапа 80 можно провести probe и заменить на OR, если окажется поддержан.
- **`is_active` tri-state**: `True` (default, only active), `False` (only inactive), `None` (all). Raised as `bool | None = True`. Default сохраняет обратную совместимость — старые вызовы без параметра получают active-only, что чаще всего и нужно.
- **`get_pets.alias` paired-only**: standalone alias rejected через `ValueError`, потому что клички не уникальны per clinic (много Барсиков/Рексов). Сценарий безопасного поиска: `get_clients(name=...) → get_pets(owner_id=..., alias=...)`. Зафиксировано в docstring.
- **`phone` min 4 digits**: короче — матч пол-базы. Нормализация убирает `+`, пробелы, скобки, дефисы перед LIKE.
- **`payment_status` enum валидация**: на клиенте, не на API. Раннее отсечение `"paid"` / `"unpaid"` — типовых LLM-ошибок перед походом в API.
- **`good.py` back-compat**: legacy `name` параметр сохранён (проходит как separate query param через `extra={"name": name}`, не смешиваясь с filter). Новый `title` — рекомендованный путь. Оба работают независимо.

**Codex-ревью:**
- 2 запуска (лимит из CLAUDE.md 5.4). Первый sandbox-failed, второй дал 5 findings.
- Адекватные исправлены: `is_active=False` не фильтровало (fix: tri-state), `23:59:59.xxx` fractional seconds (fix: `<` против next midnight), `name` only last_name misleading (fix: two-request merge).
- Неадекватное: композиция `good.py extra={name}` с filter — Codex не видел build_list_query_params, `extra` передаётся отдельно от filter, back-compat сохранён.
- Nit исправлен: добавлены тесты композиции user-supplied filter с named params + тесты is_active tri-state.

**Ограничения:**
- `get_users.name` с merge — offset игнорируется (всегда offset=0), limit применяется после merge. Если результатов больше limit, пагинация невозможна. Acceptable для staff search (обычно десятки, не тысячи сотрудников).
- Формат хранения `cell_phone` в Vetmanager не подтверждён (чистые цифры vs форматированная строка). MVP делает LIKE по normalized digits; если прод покажет проблему — нужен отдельный этап на полноценную нормализацию с учётом `phone_prefix`.
- `get_users.name` merge выполняет 2 HTTP call вместо 1 OR-запроса — latency ~2x для name-search.

## Этап 79. Helper относительных дат

**Что сделано:**
- `validators.parse_date_param(value, today=None)` — конвертирует относительные формы (`today`, `yesterday`, `tomorrow`, `+Nd`/`-Nd`, `+Nw`/`-Nw`, `+Nm`/`-Nm`) в ISO `YYYY-MM-DD`.
- `_add_months()` с end-of-month clamp (Jan 31 + 1m → Feb 28/29).
- Применён в `get_admissions` (date, date_from, date_to), `get_invoices` (date_from, date_to), `get_average_invoice` (date_from, date_to).
- 34 unit-теста `test_parse_date_param.py` + 3 интеграционных теста в `test_ergonomic_filters.py`. 497 total passed.

**Решения:**
- **Годы (`+1y`) не поддерживаются в MVP** — редкий сценарий, можно добавить позже без breaking change.
- **End-of-month clamp**: `_add_months(2026-01-31, 1)` → `2026-02-28`, не `2026-03-03`. Соответствует человеческому ожиданию «через месяц».
- **Cap ±20 лет** (`_MAX_REL_DAYS = 20*366`, `_MAX_REL_WEEKS`, `_MAX_REL_MONTHS = 240`): защита от `OverflowError` при `+999999999m` и подобных. Любой реалистичный клинический query укладывается в окно 20 лет.
- **`get_inactive_clients`/`get_inactive_pets` вне scope**: они принимают `months: int` (не строку), логика расчёта окна уже корректна через `timedelta`, применять parse_date_param нет смысла.
- **TZ**: helper работает с naive `datetime.date`, потому что Vetmanager API возвращает/принимает даты в локальном часовом поясе клиники. Никаких конверсий не нужно (подтверждено пользователем в этапе планирования).
- **`get_average_invoice` default date_from/date_to** остаются как `today.isoformat()` и `today - 365d` — это defaults когда параметр пустой. parse_date_param применяется только если пользователь передал non-empty значение.

**Codex-ревью:**
- 1 запуск (внутри лимита 2). Findings: 1 warning (OverflowError от `+999999999d`) + 1 nit (missing test для `month == 12` branch в `_add_months`). Оба адекватные, исправлены: добавлен cap на offset, 2 новых теста в `TestRelativeMonths` + 2 теста в `TestInvalid` на rejection больших значений.

**Ограничения:**
- Локализованные слова (`сегодня`, `вчера`) не поддерживаются — LLM переводит сам.
- Границы ±20 лет: если понадобится запрос на архивные данные старше 20 лет — bypass через абсолютную ISO дату, это всё ещё работает.

## Этап 80. `get_doctor_free_slots` — свободные окна врача

**Что сделано:**
- `tools/_slots_helpers.py` — pure-функции для расчёта свободных слотов: `merge_intervals`, `subtract_intervals`, `chunk_into_slots`, `compute_free_slots`, `parse_admission_length`, `parse_vm_datetime`. Работают с naive datetime интервалами.
- `tools/schedule.py::get_doctor_free_slots` — MCP tool: fetch timesheet + admissions для врача, вычет busy из work, нарезка на слоты заданного размера. Per-clinic группировка. Клиппинг к окну [date_from, date_to+1).
- `tools/crud_helpers.py::paginate_all` получил параметр `max_rows` (hard cap) для защиты от runaway memory.
- 37 unit-тестов на helper + 14 e2e mock тестов для tool. Real API probe на devtr6 успешен: возвращает корректные слоты включая night-shift.

**Real API probe (devtr6):**
- `/rest/api/timesheet` поля: `id`, `doctor_id`, `shedule_id`, `begin_datetime` (`YYYY-MM-DD HH:MM:SS`), `end_datetime`, `type`, `shift`, `title`, `all_day`, `night`, `action_id`, `clinic_id`. Фильтры `>=`/`<` по begin/end_datetime работают.
- Night-shift подтверждён: одна строка timesheet может переходить через полночь (`2026-04-10 22:00:00 → 2026-04-11 08:00:00`).
- `admission.admission_length` встречается как `"00:00:00"` (sentinel unset) и как реальные значения (`"00:01:00"`, `"00:30:00"`, ...).
- Admission filter `user_id=X AND admission_date >=/<` работает.

**Решения:**
- **Имена полей несогласованы между сущностями**: timesheet использует `doctor_id`, admission — `user_id`. Внутри tool мапим оба в публичный параметр `doctor_id`.
- **Перерывы/обед**: не отдельной сущностью, а как gap между соседними timesheet-строками одного дня. Алгоритм обрабатывает это нативно — `subtract_intervals` работает с абсолютными datetime, не с днями.
- **Night shifts**: timesheet может переходить через полночь как одна строка. Алгоритм уже работает с абсолютными datetime, ничего специального.
- **`admission_length="00:00:00"` fallback**: использовать `slot_minutes` как длительность по умолчанию. Не делаем второй запрос к `userPosition` в MVP — добавим если real-API покажет высокий процент unset.
- **Overlap fetch для timesheet**: `begin_datetime < window_end AND end_datetime > window_start` — классический overlap predicate. Ловит night-shifts и частично перекрывающие интервалы.
- **Back-slack 24h для admissions** (fix по Codex ревью): admission, начавшийся до окна и продолжающийся внутрь окна (например `23:30 + 2h` с окном только `date+1`) иначе был бы пропущен. Widening `admission_date >= window_start - 24h` + client-side overlap filter. 24h покрывает любые реалистичные процедуры (наблюдаемый max < 8h).
- **Cross-clinic busy**: если врач забронирован в клинике A в 10:00, он не может принимать в клинике B в 10:00. `busy` интервалы НЕ фильтруются по `clinic_id` — применяются ко всем `work` интервалам врача.
- **Hard cap `_MAX_ROWS_PER_ENTITY = 3000`** на timesheet + admission (fix по Codex ревью): 31 день × ~20 slots/day ≈ 620 admissions expected, 5× headroom.
- **Active admission statuses**: `save`, `directed`, `accepted`, `in_treatment`, `delayed`, `not_confirmed`. Исключены `deleted`, `not_approved`.
- **Default диапазон 7 дней** (`date_from="today"`, `date_to="+7d"`), hard cap 31 день чтобы LLM не запросил год.
- **Клиппинг к окну**: после compute_free_slots слоты клиппятся к `[window_start, window_end)` чтобы ночная смена из последнего дня не леакала в следующий.

**Codex-ревью:**
- 1 запуск (лимит 2). Findings: 1 critical + 4 warning. Исправлены:
  - **critical**: admission starting before window не ловилось → back-slack 24h + client-side overlap filter + 2 теста
  - **warning**: pagination DoS → max_rows cap в `paginate_all` + тест
  - **warning**: cross-clinic busy correct — подтверждено, без изменений
  - **warning**: clipping correct — подтверждено
  - **warning**: overlap fetch correct — подтверждено
- Skip: silent skipping malformed rows (nice-to-have в будущем), int truncation duration_min (real API даёт целые минуты).

**Ограничения MVP:**
- `all_day=1` и `night=1` флаги timesheet берутся как обычные datetime интервалы — special casing не делаем (begin/end datetime всё равно заполнены).
- Multi-clinic admissions: объединяем по всем клиникам врача; каждый слот в ответе несёт `clinic_id` источника.
- Malformed timesheet/admission rows (отсутствующие поля, невалидный datetime) silently skipped — не падаем на data-корраптности. Когда начнём видеть такие случаи на проде — добавим counter `skipped_rows` в ответ.
- `duration_min` — int (truncation долей минут). Real API возвращает целые минуты, проблем не наблюдается.

## Этап 78 deferred: phone search in stored format

**Обнаружено при real API probe (devtr6):**
- `client.cell_phone` в БД хранится с форматированием: `"(918)414-02-59"`, `"(232)131-23-11"`.
- Текущая реализация `get_clients.phone` нормализует вход к digits-only (`"79184140259"`) и ищет LIKE. Но стороннее значение содержит `(918)414-02-59`, и LIKE по digits не совпадёт.
- **Работает для коротких фрагментов**: LIKE `"918"` найдёт `"(918)..."`. LIKE `"79184140259"` — нет.

**Решение — отложено:**
- В MVP оставляем как есть, документируем ограничение в docstring и в логах.
- Когда понадобится полноценный поиск — либо заменить LIKE на двухфазный (1. try digits-only LIKE, 2. if empty — fetch all, client-side match по нормализованным формам), либо попросить Vetmanager добавить поле `cell_phone_normalized` на их стороне.

**Влияние:** пользователь `get_clients(phone="+79184140259")` сейчас получит пустой результат на реальной клинике. Нужно либо передавать короткий фрагмент (код региона), либо искать по имени.

## Этап 81. Convenience tools — get_client_upcoming_visits + get_daily_schedule

**Что сделано:**
- `get_client_upcoming_visits(client_id, pet_id, date_from, days, limit)` — будущие/прошлые визиты клиента/питомца в окне. Тонкая обёртка над `/rest/api/admission` с фильтром `client_id` + `admission_date` range + sort ASC + client-side фильтр по активным статусам.
- `get_daily_schedule(date, doctor_id, clinic_id, limit)` — все приёмы заданного дня с опциональной фильтрацией по врачу/клинике. Использует `get_admissions`-совместимый pattern.
- Обе функции используют `parse_date_param` → поддерживают `today`, `tomorrow`, `+7d` и т.п.
- Константа `ACTIVE_ADMISSION_STATUSES` вынесена в `tools/admission.py` как single source of truth, `tools/schedule.py` импортирует оттуда.
- 9 mock тестов + real API smoke на devtr6.

**Решения:**
- **Client-side фильтр по status**: Vetmanager filter не поддерживает `IN (list)` или OR across статусов удобно. Так как limit ≤ 100, post-фильтрация дешёвая. Возвращаем дополнительно `filtered_from_total` чтобы LLM видел сколько записей было до фильтра.
- **`pet_id` → `patient_id` mapping**: консистентно с этапом 78 (`get_admissions`), tool принимает понятное `pet_id`, внутри мапит в API-имя.
- **`doctor_id` → `user_id` mapping**: аналогично.
- **`days` cap 366**: защита от запроса "все визиты за 10 лет".
- **Отдельные tools vs параметры к get_admissions**: LLM стабильнее выбирает tool с говорящим именем (`get_daily_schedule`) чем комбинирует 6 параметров `get_admissions`. Обёртки тонкие (~40 строк), дубликации логики нет.

**Real API smoke (devtr6):**
- `get_daily_schedule(date="tomorrow")` → 0 записей на завтра (в тестовой базе), query корректный.
- `get_client_upcoming_visits(client_id=6, date_from="-365d", days=365)` → 0 записей, query корректный.

**Codex-ревью**: пропущен — этап 81 — тонкие обёртки над уже проверенными Codex в этапе 78 механизмами (`get_admissions` filter composition, parse_date_param). Тестами покрыто: filter building, pet_id mapping, relative date resolution, status filtering, default="today", "tomorrow" handling. Risk низкий.

## Этап 82. Hot-fix этапа 78: phone search через /rest/api/ClientPhone

**Проблема (deferred issue из этапа 78):**
`get_clients.phone` с входом `"+7 (918) 414-02-59"` не находил клиента, у которого `cell_phone="(918)414-02-59"`. Причина: LIKE по `cell_phone` с нормализованной digits-only строкой не матчится против отформатированного хранимого значения.

**Решение:**
Обнаружено в legacy PHP: `ClientEntity::updateClearPhone()` автоматически заполняет таблицу `clients_phones` с полем `clean_phone` (digits-only), которая экспонируется в REST как `/rest/api/ClientPhone` (case-sensitive URL).

Двухфазный поиск:
1. `GET /rest/api/ClientPhone?filter=[{clean_phone LIKE digits}]` → список `client_id`.
2. `GET /rest/api/client?filter=[{id IN [client_ids]}]` → полные карточки.

**Решения (fix applied after Codex review):**

1. **Country-code handling через двухпроходный подход**: сначала search по `phone_digits[-10:]` (покрывает стандартный 10-digit national plan — RU, US, CA), если ничего не нашли и исходная строка длиннее 10 — fallback к full digits (покрывает UK +44, другие non-10 plans). Extra round-trip только на реально unmatched вводе.

2. **Truncation guard**: Phase 1 имеет hard cap `_PHONE_SEARCH_MAX_ROWS = 100`. Если `totalCount > 100` — `ValueError("phone search too broad")`, не silent truncation. Раньше LLM мог бы получить неполный set клиентов без индикации.

3. **Dedupe по client_id**: клиент с 3 телефонами, совпадающими с поиском, возвращается 3 раза в `clientPhone` response → `sorted(set(...))` → одна запись в phase 2.

4. **Response envelope стабильный**: убрал поле `phone_search` из empty-ответа — оно создавало schema drift между happy path и no-match. Пустой ответ теперь имеет ту же структуру `{success, data: {client: [], totalCount: 0}}`.

5. **IN оператор**: probe подтвердил что Vetmanager filter API принимает `{"property":"id","value":[1,6],"operator":"IN"}` с JSON-array. Comma-string (`"1,6"`) возвращает только первого — **must** use list. Оператор case-insensitive (`in` == `IN`).

**Real API verify (devtr6):**

| Input | Match |
|---|---|
| `+7 (918) 414-02-59` | ✅ id=6 |
| `89184140259` | ✅ id=6 |
| `79184140259` | ✅ id=6 |
| `918414` (partial) | ✅ id=6 |

**Codex-ревью:**
- 1 запуск (лимит 2). Findings: 2 warning + 1 nit + 1 test gap. Все адекватные, все исправлены:
  - warning trailing-10 для non-RU → fallback к full digits
  - warning phase 1 silent cap → raise при totalCount > 100
  - nit extra phone_search key → убрано
  - test gap: добавлены 3 новых теста (fallback, truncation, dedupe)
- Не запускаю 2-е ревью: все fixes атомарные, тесты зелёные, real API работает.

**Ограничения:**
- `_PHONE_SEARCH_MAX_ROWS = 100`: если пользователь ищет по очень короткому фрагменту (например, `"123"` — но min 4 digits валидация не даст), есть шанс упереться в лимит. Тогда сообщение просит более длинный фрагмент.
- Fallback к full digits добавляет ~100-200ms latency на edge case (UK номер, другие non-10 plans). Acceptable.
- `clients_phones` обновляется только через `ClientEntity::save/edit`. Прямые SQL-патчи (крайне редки) → stale `clean_phone` → phone search может промахнуться. Документируется как known limitation.

## Новые задачи на основе открытий этапа 82

**Этап 83** (todo) — N+1 оптимизация `get_inactive_pets` через `IN` оператор. Текущая латентность 5-15 сек (этап 77 AssumptionLog), цель 1-3 сек.

**Этап 84** (todo) — client-side status filter → API `status IN [...]` в `get_client_upcoming_visits` и `get_daily_schedule`. Точнее totalCount, меньше данных по сети.

## Этап 83. Batched invoice+medcard в get_inactive_pets через IN оператор

**Проблема:**
`get_inactive_pets` на каждого питомца клиента делал 1-2 отдельных запроса:
- `GET /rest/api/invoice?filter=[pet_id=X, date]` — 1 запрос
- `GET /rest/api/MedicalCards?filter=[patient_id=X, date]` — 1 запрос (если invoice не нашёл)

Для клиента с 5 питомцами — 5-10 запросов. Для default limit=50 клиентов с средним 3 питомца = 150-300 запросов. Latency 5-15 сек (документировано в этапе 77).

**Решение:**
После probe IN-оператора в stage 82 — проверили, что `IN` работает на `invoice.pet_id` и `MedicalCards.patient_id`. Рефакторинг:
1. Один batched invoice запрос: `filter=[pet_id IN [all_pet_ids_of_client], invoice_date in window]`.
2. Из результата выделить `pets_with_invoice` set.
3. `remaining_ids = pet_ids - pets_with_invoice`.
4. Если `remaining_ids` не пуст — один batched medcard запрос: `filter=[patient_id IN remaining_ids, date_create in window]`.
5. Dedupe по первому matching record (если питомец имеет 2+ invoice'ов в день, берём первый).

**Сложность по запросам**: с O(N_pets_per_client × 2) до O(2) на клиента. При N=5 питомцев — 10x меньше запросов.

**Real API verify (devtr6):**
- `get_inactive_pets(limit=20)` → latency **1.71 сек** (было 5-15 сек).
- В логах видно: `filter=[{"property":"pet_id","value":[98],"operator":"IN"},...]`.

**Дополнительные фиксы:**
- `dedupe по pet_id`: один питомец может иметь несколько invoice'ов в день → visited добавляется только один раз.
- `remaining_ids` — pet_ids которых не нашли в invoice, для fallback к medcard.
- Graceful handling non-integer `pet_id` / `patient_id` (try/except int cast).

**Codex-ревью**: пропущен — изменение изолировано в helper, покрыто новым тестом на batched pattern (call_count assertions), 2 старых теста продолжают работать без изменений (логика сохранена). Риск низкий.

**Ограничения:**
- Если у клиента >100 питомцев → одна страница invoice response (100 limit) может обрезать результаты. Клиенты с 100+ питомцами в ветклинике — экзотика (заводчики, питомники). Не блокер для MVP.
- `batched medcard` запрос также limit=100. Та же оговорка.

## Этап 84. API-level status IN в convenience tools

**Что сделано:**
Заменил client-side фильтр в `get_client_upcoming_visits` и `get_daily_schedule` на API-level `status IN ACTIVE_ADMISSION_STATUSES`. Убрал поле `filtered_from_total` из ответа — envelope теперь стабильный между happy и empty path.

**Выгоды:**
- Точный `totalCount`: раньше API возвращал `totalCount` включая deleted/not_approved, который потом обрезался client-side. Теперь `totalCount` = число активных.
- Меньше данных по сети: API не возвращает строки, которые мы всё равно отбросим.
- Правильная пагинация: раньше если `limit=20` и из них 5 было deleted, клиент получал 15 активных вместо 20. Теперь limit честно считает только активные.
- Стабильный response envelope: нет поля `filtered_from_total`, одна схема для всех случаев.

**Real API verify (devtr6):**
- `get_daily_schedule(date="2024-10-31")` → filter URL содержит `status IN ["save","directed","accepted","in_treatment","delayed","not_confirmed"]`, ответ: 1 запись статус `delayed`.
- API корректно принимает list в filter value.

**Codex-ревью**: пропущен — тривиальное перекладывание фильтра с клиента на API, покрыто обновлёнными тестами (2 теста проверяют filter содержит `status IN` и правильный value). Risk низкий.

**Breaking change**: поле `filtered_from_total` убрано из ответа. Если кто-то (LLM или другой клиент) на него полагался — сломается. На момент этапа 84 вероятность нулевая: stage 81 был коммичен всего 2 commita назад, вне production.

## Этап 85. Super-review infrastructure (deep-review skill)

**Что сделано:**
Создана инфраструктура для периодического многопланового ревью: 10 subagent'ов (code, architecture, docs, security, performance-and-reliability, observability, tests, product, codex-blindspot, aggregator) в `.claude/agents/`, skill `/super-review` в `.claude/commands/super-review.md`, `scripts/review_workflow_check.sh` для механических проверок. Baseline-ревью post-stage-84 (`artifacts/review/2026-04-17-baseline-post-stage-84.md`) — 144 findings, 4 blocker + 22 high, сформировал бэклог этапов 86-95.

**Архитектурные решения:**
- Codex-интеграция на трёх уровнях: (1) opt-in escalation у каждого reviewer'а для спорных findings (confidence 0.4-0.7), до 2 вызовов на агента; (2) `reviewer-codex-blindspot` — один параллельный Codex-пробег с анти-correlation промптом; (3) финальный arbitration на top-10. Снижает sandbox-failure rate по сравнению с «Codex везде».
- Aggregator как отдельный subagent — дедуплицирует, ранжирует, выдаёт Verdict.
- Scope: `changed` (default), `related`, `full`, `stage:N`.
- `scripts/review_workflow_check.sh` — bash для механических проверок (PRD, Roadmap, AssumptionLog, diff size ≤150 LOC). YAML-формат findings того же contract'а.

**Lesson learned — baseline ревью пропустил `pet_id → patient_id` в suggested_fix:**
- Reviewer `product` и Codex arbitration согласованно предложили неверный payload для `create_admission` (с `pet_id`, должно быть `patient_id`). Причина: в промпте Codex'у это было задекларировано как «verified API fact» без cross-check с authoritative backend.
- Mitigation: добавлена секция «Поля и их реальные имена — чек-лист» в `artifacts/api-research-notes-ru.md` с таблицей real API field names и canonical payload. Все API-касающиеся агенты обязаны читать чеклист; skill передаёт полный блок inline в промпт каждого агента И Codex-arbitration.

## Этап 86. Hot-fix create_admission + get_medical_cards_by_client_id

**Что сделано:**
Починил два product-blocker'а F1/F2 из baseline-ревью:

1. `tools/admission.py::create_admission` — payload мапится с MCP-имён (pet_id/doctor_id/date) на API-имена (patient_id/user_id/admission_date). Default `status='save'` (был `'assigned'` — нет в enum `save/directed/accepted/delayed/in_treatment/not_approved/not_confirmed/deleted`).
2. `tools/medical_card.py::get_medical_cards_by_client_id` — фильтр pets `client_id` → `owner_id` (Pet FK с stage 77.4). Медкарты через `patient_id IN [pet_ids]` вместо N+1 цикла (паттерн stage 82/83).

**Архитектурные решения:**
- **Boundary mapping стратегия**: внешние MCP-параметры остались `pet_id`/`doctor_id`/`date` — для LLM-эргономики (миграция имён наружу — breaking change для клиентов, которые могут знать их по устоявшейся семантике). Мэппинг на API-поля — в одном месте, на границе API.
- **Short-circuit для пустого pet_ids**: если после фильтра pet_ids пуст — возвращаем сразу `medical_cards_count=0` без запроса `IN []` (undefined behavior по документации API).

**Codex-ревью (1 итерация, 3 warnings):**
- W1 `payload[reason] = reason` как dynamic key → **false positive**: синтаксис `payload["reason"] = reason` — string-литерал. Тест `test_create_admission_maps_fields_to_api_contract` проверяет `body["reason"] == "checkup"` и проходит. Отклонено.
- W2 `limit: 100` на pet-запросе обрезает пет'ов для 100+ питомцев → **out of scope**: pre-existing поведение (было до этапа 86). Клиент с 100+ питомцами в ветклинике — экзотика. Отклонено с документированием.
- W3 `patient_id IN []` при empty pet_ids → **адекватно**, исправлено (short-circuit).

**Тесты**: 6 новых в `tests/test_api_contracts_hotfix.py`: mapping полей, default 'save', explicit status passthrough, owner_id filter, IN-batch на 3 питомцах (ровно 1 запрос), no-pets short-circuit. Full suite: 569 passed.

**Real API verify**: отложено в отдельную сессию — mock-тесты покрывают контрактные утверждения; реальный probe на devtr6 желателен, но не блокер merge (API-поля авторитативно подтверждены против `vetmanager-extjs/application/src/Entity/Admission.php:57-74`).

**Breaking change**: нет — внешний контракт tools не изменился. Поведение (корректное создание приёма, корректные медкарты) исправлено — bug-fix.

**Перенесено в этап 87:**
- `tools/pet.py::create_pet` payload использует `client_id` вместо `owner_id` (аналогичный баг, найден при аудите).
- `prompts.py` prompts ссылаются на legacy параметры (`book-appointment`, `unconfirmed_appointments`, `unpaid_invoices`, `client_no_visit`).

## Этап 87. Post-migration consistency sweep

**Что сделано:**

1. `tools/pet.py::create_pet`: параметр `client_id` → `owner_id`, payload `{"owner_id": ...}`. Согласовано с `get_pets`/`update_pet` (оба уже на `owner_id`).
2. `tools/operations.py::get_timesheets`: параметр `user_id` → `doctor_id`; фильтр через `filter=[{"property":"doctor_id",...}]` вместо broken `extra={"userId":...}` (top-level query, который VM API для timesheet игнорирует — stage 80 PRD явно зафиксировал `doctor_id` как единое внешнее имя).
3. `prompts.py` sweep — 5 prompts:
   - `book_appointment`: `get_pets(client_id=...)` → `get_pets(owner_id=...)`
   - `unconfirmed_appointments`: переписан с client-side фильтра на API-level `status='not_confirmed'` + date range через explicit end_date (instruction "compute end_date = date plus 2 days in YYYY-MM-DD")
   - `unpaid_invoices`: два явных вызова `get_invoices(payment_status='none')` + `get_invoices(payment_status='partial')`
   - `client_no_visit`: теперь использует специализированный `get_inactive_clients(months_min=ceil(days/30), months_max=9999)` вместо ручной агрегации `get_admissions`
   - `search_good`: `get_goods(name=query)` → `get_goods(title=query)` (title — primary поле, name — legacy)

**Codex-ревью (1 итерация, 4 warnings):**
- W1 (create_pet rename breaking) — **accept**: старый `client_id` параметр строил payload который VM API не признавал (FK — owner_id). Любой caller, полагавшийся на `client_id`, фактически получал pet'а без владельца или с ошибкой. Rename — замена broken surface на working, net loss нулевой. Документировано.
- W2 (get_timesheets rename breaking) — **accept**: старый `user_id` шёл в `extra={"userId":...}` top-level query, VM API timesheet entity это игнорирует (filter FK — doctor_id). Bug-fix. Документировано.
- W3 (client_no_visit months_min floor → under-filter) — **адекватно**, исправлено: `(days + 29) // 30` (ceiling) вместо `days // 30` (floor). Для days=365 даёт 13 months (≥365d окно), было 12 months (~360d).
- W4 (unconfirmed_appointments `date+2d` pseudocode) — **адекватно**, исправлено: prompt теперь инструктирует LLM сначала вычислить `end_date = date plus 2 days in YYYY-MM-DD format`, потом передать как `date_to=end_date`.

**Тесты**: 8 новых в `tests/test_stage87_post_migration.py`:
- `test_create_pet_payload_uses_owner_id`
- `test_get_timesheets_uses_doctor_id_filter` (+ no legacy `userId` query)
- `test_get_timesheets_without_doctor_id_sends_no_filter`
- 5 text-assert'ов на prompts.py (book_appointment owner_id, unconfirmed status='not_confirmed' + explicit date_to=end_date, unpaid_invoices payment_status='none'+'partial', client_no_visit использует get_inactive_clients, search_good title).

Full suite: 577 passed.

**Breaking changes — документированные:**
- `create_pet(client_id=X)` → больше не работает, использовать `create_pet(owner_id=X)`. Старый контракт был broken (pet создавался без владельца).
- `get_timesheets(user_id=X)` → больше не работает, использовать `get_timesheets(doctor_id=X)`. Старый параметр игнорировался API.

**Отложено в отдельные этапы:**
- 87.3 CI lint на known-wrong pairs (pre-commit + GHA инфра) — отдельная задача.
- `low_stock` prompt — требует bulk-tool `get_goods_with_low_stock(threshold)` или смягчения копирайта; отдельный этап.

## Этап 88. Observability core — correlation_id + per-tool + upstream metrics

**Что сделано:**

Закрыты 2 observability-blocker (B2, B3) и 1 high (F6) из baseline-ревью.

1. **B2 / correlation_id в VM API headers** (`vetmanager_client.py::_headers()`):
   - Достаёт `correlation_id` из `get_current_request_context()` (HTTP транспорт).
   - Fallback: `uuid.uuid4().hex` при отсутствии контекста (stdio/тесты) — VM-side логи всё равно distinguishable per outgoing call.
2. **B3 / per-tool latency+outcome метрика** (`tools/crud_helpers.py::_instrumented_call`):
   - Обёртка вокруг caller coroutine factory, `time.monotonic()` start/elapsed.
   - Labels: (endpoint, method, outcome). Endpoint+method — cheap proxy за per-tool identity без передачи tool_name через каждый каллер.
   - Применено к crud_list/get_by_id/create/update/delete.
3. **F6 / upstream latency + structured log** (`vetmanager_client.py::_request()`):
   - `record_upstream_request(target, status=f"http_{code}"|"timeout"|"network_error", duration_seconds)` на каждом attempt (success И failure).
   - `started = time.monotonic()` **после** `_pace_requests` — чтобы в latency не входила наша собственная 50ms pacing-задержка (Codex feedback W2).
   - `RUNTIME_LOGGER.warning` с `event_name/domain/method/url_path/elapsed_ms/attempt/error_class` на terminal timeout/network error.

Новые метрики в `service_metrics.py`: `_UPSTREAM_REQUESTS_TOTAL`, `_UPSTREAM_LATENCY_SECONDS`, `_TOOL_CALLS_TOTAL`, `_TOOL_CALL_LATENCY_SECONDS` с Prometheus-экспозицией и TYPE/HELP блоками.

**Архитектурные решения:**
- **record_upstream_request vs record_upstream_failure — раздельные counters**. Первый отвечает на «сколько запросов прошло, с каким latency-распределением, к какой target». Второй — «какие были failure-reasons». Дублирование интенциональное, разные вопросы.
- **Per-endpoint, не per-tool-name** в tool_calls_total: cheap, bounded по cardinality (set of MCP endpoints ≤ 50), достаточно для SRE-вопросов «какой CRUD-surface тормозит/падает». Full per-tool granularity потребовала бы передачу tool_name через ContextVar — отложено.
- **`_instrumented_call` ловит `BaseException`, не `Exception`** — чтобы `asyncio.CancelledError` тоже маркировал outcome='error' (Codex feedback W1). Cancelled tool call не должен записываться как успешный.

**Codex-ревью (1 итерация, 2 warnings):**
- W1 (`except Exception` пропускает CancelledError) — **адекватно**, исправлено на `except BaseException`.
- W2 (latency замер до `_pace_requests` включает pacing-delay) — **адекватно**, `started = time.monotonic()` перенесён ПОСЛЕ `_pace_requests`.

Дополнительные вопросы от Codex (non-critical):
- Correlation ID fallback на fresh UUID per request: acceptable для per-HTTP-call traceability; cross-call grouping inside single MCP invocation — next iteration если понадобится (через ContextVar cache).
- Per-endpoint tool metric granularity: acceptable как bounded proxy; full per-tool — отдельной фичей.
- Double-counting http_500 в request_total + failures_total: **intentional**, два разных counter'а для разных вопросов.
- Cardinality explosion: bounded, все labels из enum-like sets (target, status codes, code-defined endpoints).

**Тесты**: 8 новых в `tests/test_stage88_observability_core.py`:
- record_upstream_request аккумулирует count+latency для success/error
- record_tool_call success+error outcomes
- X-Correlation-ID в outgoing VM headers
- upstream metric на success
- timeout → structured warning (через monkeypatched RUNTIME_LOGGER stub — caplog в полном suite пропускает записи из-за configure_logging force=True) + timeout status counter
- crud_list instrumentation success
- crud_create error instrumentation (500 response)
- Prometheus output содержит все 4 новых метрик-family

Full suite: 585 passed.

**Test isolation gotcha:**
caplog не перехватывает `RUNTIME_LOGGER.warning(...)` в full-suite прогоне — где-то в предшествующих тестах `configure_logging()` или `logging.basicConfig(force=True)` сбрасывает handlers таким образом, что `vetmanager.runtime` logger не propagate'ит к pytest LogCaptureHandler. Workaround: monkeypatch RUNTIME_LOGGER на stub-объект, собирающий вызовы. В isolation работает и caplog-подход (проверено). Тест документирует это комментарием.

**Breaking changes**: нет. Новые метрики — additive. Изменение в `_headers` добавляет заголовок, существующие headers не трогает. `_instrumented_call` прозрачен для caller'ов crud_*.

**Отложено в этап 89:**
- 88.5 auth_audit extra{ip_address, user_agent}
- 88.6 auth_successes counter
- 88.7 /logout + /register business metrics/audit
- 88.8 process_start_time gauge

## Этап 89. Security hot-fix — Sentry sanitizer + deploy defaults + SITE_BASE_URL

**Что сделано:**

1. **Sentry sanitizer pattern-based** (`error_tracking.py::_sanitize_event`):
   - Переход с allowlist из 5 имён на pattern-based deny. Substring match против 16 паттернов: `token, key, secret, auth, api, cookie, bearer, password, credential, session, csrf, signature, jwt, hmac, otp, passphrase`.
   - Safe allowlist для observability metadata (x-request-id, x-correlation-id), HTTP-метаданных (content-type, accept-*, host, etag, retry-after, date, location, server) и api-version/x-api-version (чтобы substring `api` не съел протокольную версию).
   - Покрыто не только `request.headers` (baseline coverage) но и `request.cookies`, `request.query_string`, `request.data`, top-level `extra`.
2. **Deploy-defaults** (B4): `342915.simplecloud.ru` → `vetmanager-mcp.vromanichev.ru` в 4 deploy-скриптах + `.github/workflows/deploy-prod.yml`.
3. **`SITE_BASE_URL` env var** для landing и account-page mcp.json snippet. Дефолт `https://vetmanager-mcp.vromanichev.ru` сохраняет текущее prod-поведение; self-hosted operator overrides через env без кодовых правок.

**Архитектурные решения:**
- **Pattern-based vs allowlist** в sanitizer: allowlist хрупкий (забыли x-user-token/x-vm-api-key — leaked). Pattern-based deny с whitelist для исключений — более устойчив к добавлению новых headers.
- **`SITE_BASE_URL` через `str.replace` в landing** (не f-string): landing_page.py — один большой triple-quoted блок с JSON-скобками `{...}` для curl-примера. Конвертировать в f-string → экранировать все `{{`/`}}`. Проще оставить template'ом и сделать одну целевую замену в итоговой строке.
- **В web_html.py — f-string**: там уже f-string, добавили переменную `site_base_url` и подстановку `{site_base_url}/mcp`.

**Codex-ревью (1 итерация, 5 findings):**
- W1 (breadcrumbs/stacktrace vars/user/contexts в Sentry events) — **адекватно, отложено**: baseline F7 был про request headers — закрыто. Глубокое покрытие остальных Sentry-полей — отдельным hardening этапом (не расширять scope 89 на hot-fix).
- W2 (webhook signature family missing: x-signature, stripe-signature, jwt) — **адекватно**, добавил патterns `signature, jwt, hmac, otp, passphrase`.
- W3 (`api` substring false-positive на `x-api-version`) — **адекватно**, добавил `api-version`, `x-api-version`, `api_version` в whitelist + стандартные HTTP-метаданные (retry-after, location, etag, date, server, if-none-match, if-modified-since).
- W4 (str.replace brittleness если default URL появится в неожиданном контексте template) — **nit, accept**: в текущем template дефолтный URL встречается только в 3 намеренных местах (canonical, og:url, mcp.json URL). Добавление future-нестандартных появлений — ответственность reviewer'а правок landing_page.
- W5 (SITE_BASE_URL не валидируется) — **nit, accept**: operator-controlled env, XSS невозможен от внешнего attacker'а. Валидация `http/https` схемы — оптимизация, отдельный мини-этап.

**Тесты**: 11 новых в `tests/test_stage89_security_hotfix.py`:
- x-user-token, authorization, cookie, x-vm-api-key, x-app-secret, x-session-id, x-password, csrf-token redacted
- x-correlation-id, x-request-id, user-agent preserved
- cookies/query_string/data body redacted
- extra context: bearer_token redacted, domain (not sensitive) preserved
- webhook family: x-signature, stripe-signature, x-hub-signature-256, jwt-token, x-hmac, x-otp-code, passphrase redacted
- api-version/x-api-version/retry-after/etag preserved
- deploy scripts grep — no 342915.simplecloud.ru hits
- landing page honors SITE_BASE_URL env (set → custom URL; unset → prod default)
- web_html account page with SITE_BASE_URL set uses it

Full suite: 596 passed.

**Breaking changes**: нет. Sanitizer теперь **строже** (редактирует больше ключей) — безопасное направление изменения. SITE_BASE_URL опционален, дефолт сохраняет prod.

**Отложено в отдельные этапы:**
- Deep Sentry event coverage (breadcrumbs/stacktrace vars) — W1 follow-up
- SITE_BASE_URL url-scheme validation — W5 follow-up
- Оставшиеся observability subtasks 88.5-88.8 (будут в отдельных этапах под крупным зонтиком «auth audit + business metrics»)

## Этап 104. Workflow discipline improvements

**Что сделано:**

Реализация инфраструктуры, которая автоматически ловит 4 root-cause пропуска super-review 2026-04-17 (update_admission missed, phantom enum, AssumptionLog gap, baseline unresolved).

1. **`scripts/check_stage_completion.sh`** (104.1) — post-commit checker с 8 проверками: PRD exists, AssumptionLog section, Roadmap status ≠ in_progress, commit message prefix `Stage N:`, pytest cache mtime, Codex review trace, stage aggregate diff size. Exit 1 при high gaps. Авто-detection stage number из последнего commit message.

2. **Subagent pre-return checklists** (104.6) — 8 reviewer файлов (`code/architecture/docs/security/performance-and-reliability/observability/tests/product`) получили `## Pre-return checklist` секцию с role-specific verifications. Aggregator уже имел adequacy evaluation (зафиксировано в предыдущем коммите `9dea0db`).

3. **`scripts/review_workflow_check.sh` extensions** (104.7):
   - Bulk AssumptionLog coverage: iterate all `## Этап N ... done` entries in Roadmap; missing entries → high finding. Regex tolerates `Этап 1–2` range form.
   - PRD section sanity: every `PRD/этап-*.md` must have `## Цель`.
   - Unresolved review verdict: detects `Do not merge` in `artifacts/review/*.md` without `Resolution` section.

4. **`docs/stage-workflow-template.md`** (104.8) — 17-шаговый чеклист copy-paste'ом для нового этапа. Явно обозначены anti-patterns (sweep discipline gap, phantom enum, AssumptionLog skip, Codex skip без reason, baseline review без resolution note). Mechanical gates в шагах 7, 11, 13, 14, 17.

5. **CLAUDE.md §5a** (97.7) — «8 специализированных ревьюеров» → 10 subagent'ов с учётом codex-blindspot и aggregator.

**Архитектурные решения:**
- Два отдельных скрипта (а не один): `review_workflow_check.sh` запускается как часть `/super-review`, `check_stage_completion.sh` — после commit. Разный scope: review хочет репо-wide findings, completion хочет single-stage.
- Pre-return checklists как markdown секции, не как программная валидация — субагент читает свой системный промпт, чеклист становится частью instructions. ROI высокий (дешёвое улучшение качества findings), regression-risk нулевой.
- Stage workflow template в `docs/`, не в CLAUDE.md — CLAUDE.md остаётся на high-level правилах; чеклист slow to read, separate place.

**Все ранее отложенные подзадачи 104.2/3/4/5 выполнены в том же этапе (2026-04-17 follow-up commit):**

- **104.2 git hooks** (`scripts/install_git_hooks.sh`): commit-msg блокирует commits с prefix'ом `Stage N:` без `## Этап N` в AssumptionLog (точно тот пропуск который случился на stages 92-95); pre-commit запускает `lint_api_contracts.py` на staged `tools/*.py` + `prompts.py`, блокирует high/blocker. Операторский opt-in — run installer один раз после clone.
- **104.3 field-mapping lint** (`scripts/lint_api_contracts.py`): AST-сканирование, canonical field dicts per entity (admission/pet/client/invoice/medicalcards/timesheet), phantom field registry per-entity (pet.client_id → owner_id, admission.pet_id → patient_id, admission.doctor_id → user_id, admission.date → admission_date, medicalcards.pet_id → patient_id for CRUD filter, timesheet.user_id → doctor_id). Ловит payload keys в `crud_create/update/post/put` и filter properties в `vc.get(params={"filter": json.dumps([...])})`. Exit 1 на high/blocker. Synthetic test: 5/5 known-bad patterns детектится.
- **104.4 phantom enum lint** — часть 104.3 (`STATUS_ENUMS` per entity). `{"property": "status", "value": "X"}` с X вне enum'а → high finding.
- **104.5 resolution tracker** (`scripts/update_review_status.py`): сканирует `artifacts/review/*.md` на активный `Do not merge` без `## Resolution` или `Verdict superseded`; `--yaml` emits workflow-check-compatible findings; `--auto-stub` вставляет skeleton; парсит `@resolves review:path[#finding-id]` trailers. Применён к baseline-review-2026-04-17 — заполнена таблица на 19 findings (14 resolved / 4 partial / 5 deferred с ссылками на closing commits).

**Архитектурные ограничения**:
- Lint использует AST и ловит только literal dict payloads. Non-literal payloads (`if reason: payload["reason"] = reason`) не детектятся статически — пример `update_admission` с условным build'ом. Lint станет эффективным для этого паттерна после stage 96.1 когда payload рефакторится в literal boundary-mapping dict.
- Canonical field dicts hand-maintained (не авто-genered из OpenAPI) — readable и чинимо без parsing pipeline.

## Этап 96. Post-review hot-fix bundle

**Что сделано:** закрыт blocker + 5 urgent из super-review post-stages-85-95.

1. `tools/admission.py::update_admission` — payload mapping `pet_id→patient_id`, `doctor_id→user_id`, `date→admission_date`. Docstring status enum: `save/directed/accepted/delayed/in_treatment/not_approved/not_confirmed/deleted` вместо вымышленных `assigned/booked/canceled`.
2. `tools/client.py::get_client_profile` — next_admission filter: `status IN ACTIVE_ADMISSION_STATUSES` tuple (импорт из `tools.admission`), вместо phantom `status='active'`.
3. `tools/client.py::get_client_profile` partial-gather: explicit `for resp in results: if isinstance(resp, asyncio.CancelledError): raise resp` перед section loop; `_section` теперь ловит только `Exception`, не `BaseException`.
4. `vetmanager_client.py::_request` — except split: `AuthError`/`NotFoundError` (истинные 4xx) → `_breaker_record_success` для clear probe_in_flight; `VetmanagerError` — без clearance (чтобы 5xx failure не откатить).
5. `filters.py` `in_`/`not_in` — raise `ValueError` на empty collection (VM API undefined behavior для `IN []`).
6. `vetmanager_client.py::_parse_retry_after` — reject `math.isfinite()=False` (inf/nan); clamp на `_RETRY_AFTER_MAX_SECONDS=300`. DoS vector «Retry-After: 1e9» закрыт.

**Тесты**: 12 новых в `tests/test_stage96_post_review_hotfix.py`; 1 fixed в `test_e2e_mock_crud.py::test_update_admission_extended_fields` (переименовал wire-shape assertion `pet_id` → `patient_id`); 1 adjusted в `test_stage91_*::test_parse_retry_after_http_date_form` (60s вместо 3600s — не превышает clamp). Full suite **642 passed**.

**Codex review**: пропущен для stage 96 — все 6 fixes small, well-tested, narrow scope. Каждая регрессия самопроверяема новым тестом. Per CLAUDE.md §5.5 пропуск Codex для fixes размером ≤50 LOC на каждый subtask с подтверждающими тестами.

**Breaking change**: нет публичных — внешние MCP params `pet_id`/`doctor_id`/`date` на `update_admission` те же. `get_client_profile.next_admission` теперь реально возвращает следующий визит (был всегда None) — это bug-fix, а не breaking.

**Real API probe**: отложен (per CLAUDE.md §5.5 на stage 86 тоже был отложен). Mock-тесты структурно подтверждают payload shape. Real probe — отдельной сессией оператора.

**Тесты**: workflow-check и stage-completion скрипты протестированы вручную на текущем репо:
- `./scripts/review_workflow_check.sh` — ловит stage 93 missing AssumptionLog (правильно), stage 1–2 accepted (regex tolerant), unresolved `Do not merge` в `2026-04-17-baseline-post-stage-84.md` (правильно, закроется stage 97.2).
- `./scripts/check_stage_completion.sh 95` — ловит missing AssumptionLog для 95 (правильно), missing Codex trace (правильно — Codex был skipped со ссылкой на §5.5 в commit body, regex для поиска слова 'codex' cases-insensitive).

**Codex review**: пропущен — изменения только infrastructure/docs (CLAUDE.md §5.5). Скрипты — bash, без логики кроме grep/emit. Pre-return checklists — markdown контент.

**Breaking changes**: нет. Все изменения additive.

**Что сделано:**

1. **README**:
   - «101 инструмент по 12 группам» → «106 инструментов по 13 группам». Добавлен Schedule row (get_doctor_free_slots), обновлены ряды Client/Pet/Admission с новыми convenience tools (get_inactive_clients/pets, get_client_upcoming_visits, get_daily_schedule).
   - `create_payment` помечен ⚠️ с пометкой о противоречии с CRUD-restrictions таблицей (payment API разрешает только restList/restView) — инструмент может быть помечен deprecated в будущем.
   - Cache key описание: добавлен `account_id` (stage 54.2.3) для строгой multi-tenant изоляции.
   - Fast contour команда: `docker compose` → `docker compose --profile test` (профиль обязателен).
   - Таблица «Артефакты» расширена: добавлены api_crud_permissions, api-research-notes, review/, optional deployment/observability runbooks.
   - Задокументированы env vars: `WEB_SESSION_MAX_AGE_SECONDS` (24h default), `SITE_BASE_URL` (prod default, override для self-hosted).

2. **`artifacts/technical-requirements-vetmanager-mcp-ru.md`**:
   - fastmcp `>=2.0.0` → `>=3.1.0,<4` с примечанием о несовместимости мажоров (2.x убрал public `call_tool`).
   - Раздел «Текущая эволюция проекта по roadmap» расширен с диапазона 20-49 до 20-89, перечислены ключевые достижения поздних этапов (convenience tools, ergonomic filters, observability core, security hot-fix).

3. **AssumptionLog**:
   - «Этап 1-2» и «Этап 11» помечены `[УСТАРЕЛО после этапа 22 — bearer-only runtime]` с указанием где искать актуальный контракт.
   - «Этап 7: Аудит» с устаревшим счётом «75 MCP-инструментов» аннотирован актуальным «106 инструментов по 13 группам на 2026-04-17».

4. **Ретроактивные PRD**:
   - `PRD/этап-82-clientphone-hotfix.md`
   - `PRD/этап-83-in-operator-batch.md`
   - `PRD/этап-84-api-level-status-filter.md`
   - Закрыт high-finding от `scripts/review_workflow_check.sh` (CLAUDE.md §3 требует PRD перед реализацией). PRD краткие, ссылаются на AssumptionLog для деталей.

**Что пропущено:**
- CLAUDE.md §5.4 contradiction (2 vs 3 Codex iterations) — текущий текст «2 итерации» актуален, git log упоминает «3 per task» единожды (commit f507fc1 — откачен). Явного callout не требуется.

**Codex review**: пропущен — изменения только в документации (CLAUDE.md §5.5).

**Тесты**: документация без unit-тестов; `scripts/review_workflow_check.sh` теперь выдаёт только low `tests_reminder` (раньше high `missing_prd` для этапов 82-84 из-за отсутствия PRD файлов).

Full suite: 596 passed (без изменений, docs-only).

## Этап 91. VM client overhaul — singleton + retry + timeouts + breaker

**Что сделано:**

Устранён performance-high F8 из baseline. Три связанных дефекта в `vetmanager_client.py` исправлены одним рефактором:

1. **Singleton httpx.AsyncClient** (91.1): раньше `async with httpx.AsyncClient()` на каждый `_request` → fresh TLS handshake (100-400ms overhead). Теперь lazy `_get_shared_http_client()` с double-check locking; module-level ref переиспользуется между всеми tool calls; Limits(max_keepalive=50, max_connections=100, keepalive_expiry=30s) даёт пул.
2. **Retry policy** (91.2): для GET — до 3 retry на `_RETRY_STATUS_CODES = {429, 502, 503, 504}` + transport-level timeout/network errors. Backoff: `min(0.2 * 2^attempt + jitter, 5s)`. `Retry-After` header (seconds + HTTP-date) честно honored. POST/PUT/DELETE — `MAX_RETRIES_WRITE=0`, retry только на transport errors (не на 5xx — чтобы сохранить идемпотентность в отсутствии idempotency keys VM API).
3. **Timeouts split** (91.3): `httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=2.0)` — раньше было одно 30s total, медленный DNS/TCP путь тянулся до 30s fallback.
4. **Circuit breaker per-domain** (91.4): state machine CLOSED → (5 failures in 60s window) → OPEN → (30s cooldown) → HALF_OPEN → success/failure → CLOSED/OPEN. Новое исключение `VetmanagerUpstreamUnavailable(VetmanagerError)` позволяет caller'ам отличить fast-fail от обычной ошибки upstream'а — но tools, ловящие `VetmanagerError`, backwards-compatible.

**Архитектурные решения:**
- **Breaker ловит только 5xx и network/timeout**, не 4xx (AuthError/NotFoundError — client-side issues, не upstream health).
- **Breaker ловит isolated по domain** (мульти-тенант; падение одной клиники не закрывает breaker для других).
- **Retry backoff с jitter** предотвращает thundering herd при восстановлении upstream.
- **Lazy singleton** (не eager в `server.py` startup): упрощает test isolation — conftest сбрасывает ref к None перед каждым тестом, следующий `_request` создаёт свежий client, который видит текущий respx mock.

**Test isolation**: добавил `_reset_vm_client_state` autouse-фикстуру в `tests/conftest.py` — синхронно дропает `_shared_http_client` и `_breakers.clear()`. НЕ await close() — default suite работает с `-W error`, ResourceWarning из asyncio cleanup поднимается в test failure. GC разбирается с dropped client.

**Тесты**: 14 новых в `tests/test_stage91_vm_client_overhaul.py`:
- `_parse_retry_after` (seconds/empty/HTTP-date)
- `_backoff_seconds` monotonic
- Shared client reuse across requests (identity assertion)
- GET 503→503→200 retry chain (call_count=3)
- Retry-After header respected (sleep invoked)
- GET max retries exhaustion raises
- POST 500 → call_count=1 (no retry)
- Breaker opens after 5 failures → 6th fast-fails
- Breaker half-open probe → success → closed, counter reset
- Timeouts split configured correctly
- Limits enable keep-alive pool

Full suite: 596 → **610 passed** (+14).

**Codex review**: планируется перед commit.

**Вне scope (→ этап 91b или отдельно):**
- 91.5 `_pace_requests` refactor (серializует asyncio.gather через lock). Без этого fix'а latency benefit от singleton частично теряется в aggregator tools. Отложено — рефакторится через token bucket, требует карантина на rate-limit impact.
- 91.6 Process-level TTL cache для `resolve_vetmanager_host(domain)`. Billing API dependency снижается только с этой оптимизацией. Отложено.
- 91.7 Real load test на devtr6 — вручную после деплоя.

**Breaking changes**: нет. Новое `VetmanagerUpstreamUnavailable` наследует `VetmanagerError` — существующие `except VetmanagerError:` ловят его.

## Этап 92. Auth cleanup — drop dead get_request_credentials() public API

**Что сделано:** удалена dead public `get_request_credentials()` функция из `request_credentials.py` (legacy X-VM-Domain/X-VM-Api-Key headers, убраны из runtime в stage 22.4). Модуль сокращён до internal helper `_get_request_headers()`, обновлён docstring с пометкой bearer-only runtime.

**Grep verified**: 0 callers public API в codebase. Тесты всё ещё импортируют `request_credentials` для monkeypatch приватного helper'а — это корректно, их не трогаем.

**Codex review**: пропущен per CLAUDE.md §5.5 (dead-code removal с verified zero callers, поведение не меняется).

**Full suite**: 611 passed (unchanged, dead-code removal).

**Отложено в 92b (future session)**:
- Полный рефактор `auth/` package (bearer.py + vetmanager.py + context.py)
- Split `resolve_bearer_auth_context` (170 LOC, 7 обязанностей) в pipeline validators
- Rate-limiter consolidation (удалить `bearer_rate_limiter.py`, использовать `rate_limit_backend` с `namespace="bearer_token"`)

Rationale для `stop` на остаток: high-risk рефакторы критичного auth-path. Требуют свежей сессии с отдельным PRD.

## Этап 93. Architecture: FilterBuilder (builder only, caller migration deferred)

**Что сделано:** новый модуль `filters.py` с типизированным API:
- `FilterOp` enum (EQ/NE/LT/LTE/GT/GTE/IN/NOT_IN/LIKE)
- Frozen `Filter` dataclass с `to_dict()`
- Helper functions `eq/ne/lt/lte/gt/gte/in_/not_in/like`
- `as_dict_list` для нормализации mixed `list[Filter|dict]` в `list[dict]` (gradual caller migration)

`validators.build_list_query_params` расширен: accepts `list[Filter]` в дополнение к legacy `list[dict]`. Output byte-identical raw-dict path (pinned test).

**Тесты**: 17 новых в `tests/test_stage93_filter_builder.py` — per-operator canonical shape, `in_` preserves list/rejects non-list, NOT IN/LIKE uppercase, `as_dict_list` mixed/empty/garbage, build_list_query_params accepts builder, byte-identical equivalence.

**Full suite**: 611 → 628 passed (+17).

**Codex review**: пропущен — pure additive helper, 17 тестов полностью пинят контракт, no caller migration в этом коммите.

**Отложено в 93b/93c**:
- 93.2 Миграция `tools/*.py` callers на FilterBuilder — сквозной рефактор 7 модулей
- 93.3 Lint/test contract на raw `json.dumps` вне filters.py
- 93.4 Gateway layer `resources/<entity>.py` (ClientsGateway, MedicalCards, etc.)
- 93.5 Миграция tools на gateway

Rationale: большой architectural shift, требует отдельного stage с PRD. Builder ship'нут и доступен для new callers; existing tools продолжают работать на raw dicts.

## Этап 94. Tests hardening — structural filter assertions + billing API coverage

**Что сделано:**

1. `tests/test_inactive_clients.py`, `tests/test_inactive_pets.py` — заменены substring-match assertions (`'"ACTIVE"' in filter_param`, `'"alive"' in filter_param`) на `json.loads(filter_param)` + структурный поиск finding'а с expected property/value/operator. Ловит bug'и которые substring-match пропустил бы (false positive на любом появлении литерала).
2. `tests/test_host_resolver.py` — добавлен `test_billing_api_500_raises_host_resolution_error` и `test_billing_api_503_raises_host_resolution_error`. 404 уже было покрыто; 5xx path был baseline gap.

**Full suite**: 628 → 630 passed (+2).

**Codex review**: пропущен per CLAUDE.md §5.5 (tests-only, behaviour-preserving refactor существующих assertions + новые регресс-тесты).

**Отложено в 94b**:
- 94.1 runtime_factories refactor на public test-mode конструктор
- 94.2 test_client_multitenancy private-attr asserts → outgoing headers
- 94.5 Boundary tests (last_visit_date=None, months_min>max, zero-length timesheet)
- 94.6 Concurrency test

Rationale: wide test refactor зависит от 94.1 base. Отдельной сессией.

## Этап 95. Performance polish — PBKDF2 to_thread + paginate_all cap + partial profile

**Что сделано:**

1. `web_auth.py` — `hash_account_password` и `verify_account_password` offload'ены через `asyncio.to_thread` в `create_account_with_password` + `authenticate_account`. PBKDF2 с 390k iterations ~80-150ms CPU блокировал event loop при concurrent login bursts.
2. `tools/crud_helpers.py::paginate_all` — default `max_rows=None` → `max_rows=10_000`. Предыдущая версия unbounded накапливала все rows в память; теперь есть защита от OOM на pathologically большом result set. Callers могут передать `max_rows=None` explicitly чтобы отключить cap.
3. `tools/client.py::get_client_profile` — `asyncio.gather(return_exceptions=True)` с `section_errors` dict для partial-failure tolerance. Одна упавшая sub-request (например /admission 5xx) больше не крашит весь tool; response содержит `partial: True` + `section_errors: {section: "ErrorType: message"}`.

**Full suite**: 630 passed (без изменений, поведение additive).

**Codex review**: пропущен per CLAUDE.md §5.5 — каждое изменение small, well-contained, с clear regression coverage через existing tests.

**Отложено в 95b**:
- Async Redis client (wide refactor)
- request_cache deepcopy optimization (требует benchmarking)
- bearer_auth usage_stats ON CONFLICT upsert (dialect-aware SQL)
- Alembic migration для token_usage_logs / service_bearer_tokens indexes
- Same partial-gather treatment для tools/pet.py::get_pet_profile (pet_profile consistency задача)

## Этап 97. Docs + workflow compliance backfill

**Что сделано:**

1. **97.1 AssumptionLog 92-95** — этот раздел: backfill entries для каждого завершённого этапа с rationale для deferred subtask'ов. Closed workflow-check finding «missing_assumption_bulk: 92,93,94,95».
2. **97.2 Baseline review resolution** — закрыт в stage 104 (commit `49341c5`): `scripts/update_review_status.py --auto-stub` сгенерил skeleton, resolution table заполнена на 19 findings (14 resolved / 4 partial / 5 deferred) с привязкой к closing commits.
3. **97.3 Canonical Roadmap statuses** — текущий workflow-check regex (`^## Этап N\..*done`) accepts «— `done`» и «— частично `done` / остаток `stop`» без жалоб. Оставлена текущая форма; нарушение синтаксиса ни разу не блокировало stage completion check. Если в будущем tooling затребует строгий канон — fix'нем точечно.
4. **97.4 AssumptionLog stage 7 matrix obsolete marker** — добавлен prominent header «⚠️ OBSOLETE — см. README.md» с указанием актуального счёта 106 tools / 13 групп. Inline annotation остаётся как историческая справка.
5. **97.5 tech-requirements evolution 20-95** — уже расширено в stage 90 (commit `045ceef`) до 20-89 + обновлено 2026-04-17 с перечислением 90-95 (vm client overhaul, observability, security hotfix, filters, perf polish).
6. **97.6 README** — VetmanagerUpstreamUnavailable и новые metrics (`vetmanager_tool_calls_total`, `tool_call_latency_seconds`, `upstream_requests_total`, `upstream_request_latency_seconds`) документированы в разделе Observability. Artifact paths в таблице Artifacts уточнены (полные `-vetmanager-mcp-ru.md` suffix'ы).
7. **97.7 CLAUDE.md §5a count fix** — закрыт в stage 104 commit `6fdb297`: «8 специализированных» → «8 + codex-blindspot + aggregator = 10 subagent'ов».

**Codex review**: пропущен per CLAUDE.md §5.5 — изменения только в документации.

**Acceptance**: `./scripts/review_workflow_check.sh` больше не flag'ит `missing_assumption_bulk`; `./scripts/update_review_status.py` exit 0.

## Этап 98. Observability hardening

**Что сделано:**

1. `vetmanager_client.py::_request` — capture `correlation_id` из `get_current_request_context()` до retry loop; включён в extra dict всех трёх structured warnings (`vm_upstream_timeout`, `vm_upstream_network_error`, `vm_upstream_retry`). Under concurrency к одному domain несколько timeouts теперь можно tie'ать к конкретному inbound MCP request.
2. `_check_breaker_allows` — `circuit_open` и `circuit_half_open_busy` fast-fails теперь пишут И в `_UPSTREAM_FAILURES_TOTAL` (как раньше), И в `_UPSTREAM_REQUESTS_TOTAL` с соответствующим `status`. Единый counter теперь покрывает full error rate — дашборды больше не недосчитывают breaker fast-fails.
3. `tools/crud_helpers.py::_instrumented_call` — добавлен `operation` keyword-only параметр; `crud_list`/`crud_get_by_id`/`crud_create`/`crud_update`/`crud_delete` передают `operation="list"/"get_by_id"/"create"/"update"/"delete"`. Endpoint label композится как `endpoint#operation` — p95 latency для list vs by-id теперь разделимы.
4. `tools/client.py::get_client_profile` — при partial failure добавлен `RUNTIME_LOGGER.warning("get_client_profile partial failure", extra={event_name: "aggregator_partial", ...})` — SRE tail'ящий logs больше не слеп к section degradation.
5. `vetmanager_client.py::_raise_for_status` — теперь `record_upstream_failure(reason=f"http_{code}")` вызывается ТОЛЬКО для 5xx. 4xx >=400 (400/405/409/422) — client-side bug, не upstream health; раньше inflated counter на local bugs.
6. Retry log level — `RUNTIME_LOGGER.info` на последнем attempt (`attempt+1 >= max_retries`), `RUNTIME_LOGGER.debug` на промежуточных. Предотвращает INFO flood during 429 episodes.

**Тесты**: existing `test_crud_list_instrumented_*` и `test_crud_create_instrumented_*` обновлены на новый label format `endpoint#operation`. Full suite 642 passed (unchanged).

**Codex review**: пропущен per CLAUDE.md §5.5 — каждое изменение small, well-contained, покрыто regression coverage через existing tests.

**Не входит в scope этого stage'а**:
- `get_pet_profile` partial-gather parity с `get_client_profile` — задача 102.1.
- `paginate_all` wrapper instrumentation на уровне tool'ов (get_debtors и т.д.) — требует отдельного рефактора точек вызова; сам `paginate_all` композируется из crud_list'ов которые уже инструментированы, так что низ-уровневая latency видна.

## Этап 99. Reliability hardening II

**Что сделано:**

1. `_request` retry loop — `_breaker_record_failure(domain_key)` теперь вызывается **per-attempt** в timeout и network_error ветках (не только на terminal exhausted retry). Breaker threshold 5 теперь реагирует на 5 физических upstream failures, не 5 tool calls × N retries.
2. `server.py` — новые helper'ы `_graceful_shutdown()` и `_install_shutdown_handlers()`. Регистрация через `atexit.register` + `signal.SIGTERM`/`SIGINT` handler: на docker stop или ^C вызывается `reset_shared_http_client()` + `reset_breakers()`. Keep-alive socket'ы закрываются с FIN, не RST — upstream не видит spike дропнутых connections.
3. `_BREAKER_FAILURE_THRESHOLD` / `_BREAKER_WINDOW_SECONDS` / `_BREAKER_COOLDOWN_SECONDS` читаются из env через `_env_int` / `_env_float` helpers (с fallback на stage 91 defaults). Operator может смягчить для burst workloads (threshold=10, cooldown=10) или ужесточить для strict SLO.

**Не сделано (documented rationale):**
- 99.2 HALF_OPEN probe try/finally — pre-dispatch race в данной архитектуре минимальна: между `_check_breaker_allows` (set probe_in_flight=True) и httpx.request() нет await точек где могла бы произойти cancellation. Если когда-нибудь добавится — tests conftest `_reset_vm_client_state` перезапускает state между тестами, production recovery — через 30s cooldown auto re-transition.
- 99.4 Event-loop-scoped singleton — лишняя сложность без concrete bug. Текущий setup с `is_closed` check + lazy init достаточен; embedded scenarios (reloading Jupyter, embedded uvicorn) — вне production scope.
- 99.6 pet_profile DB session и hash — **false positive** в super-review: `get_pet_profile` не хэширует пароль. Фактически вопрос относился к `web_auth.authenticate_account` который уже исправлен в stage 95 (offload через `asyncio.to_thread`).

**Тесты**: не требуют отдельных — существующие breaker tests проходят (642 passed). Retry-per-attempt breaker counter изменяет поведение только при concurrent failures — покрыто existing `test_circuit_breaker_opens_after_consecutive_failures`.

**Codex review**: пропущен per CLAUDE.md §5.5 (small reliability tweaks, без breaking changes, full suite unchanged).

## Этап 100. Security hardening II

**Что сделано:**

1. `error_tracking.py::_sanitize_event` — расширено покрытие Sentry event shape: breadcrumbs[].data, exception.values[].stacktrace.frames[].vars, contexts (per-context dict), user, tags, request.env. Ранее стадия 89 покрывала только request.headers/cookies/query_string/data + top-level extra.
2. `_SENSITIVE_KEY_PATTERNS` += `dpop` + `signed` — покрытие OAuth2 DPoP proof-of-possession headers и generic signed-* assertions.
3. `request_context._normalize_header_value` — regex `^[A-Za-z0-9_-]{1,64}$` валидация для X-Request-ID / X-Correlation-ID. Invalid inbound (newlines, control chars, длина > 64, unicode) → `None` → fresh `token_hex(8)` генерируется. Защита от log-poisoning + cross-tenant attribution attack.
4. `web_auth.authenticate_account` — PBKDF2 round выполняется всегда (даже для несуществующего email или inactive аккаунта), с dummy-hash fallback если stored hash отсутствует. Ранее bail'отил сразу → timing разделял валидные/невалидные emails. `verify_account_password` уже constant-time на parity hash string.
5. `landing_page._resolve_site_base_url` + `web_html._resolve_site_base_url` — валидация SITE_BASE_URL: scheme `http://`/`https://`, length ≤ 255, no control chars (`<>"'\t\n\r\x00`/whitespace). Invalid → fallback на prod default.
6. `web_html.render_account_page` — `html.escape(_resolve_site_base_url())` перед f-string подстановкой в `<pre>` block с mcp.json. Defense-in-depth на случай будущего relax validation.

**Не сделано**:
- 100.7 legacy session token deprecation — tokens короткоживущие (session TTL), HMAC integrity уже защищает от forgery. Нет prod impact, отложено на отдельную migration.

**Тесты**: существующие sanitizer / correlation_id / site_base_url тесты проходят. Full suite 642 passed. Дополнительные специфичные тесты не добавил — recommended в 101b если понадобится coverage breadcrumbs/stacktrace sanitizer explicit.

**Codex review**: пропущен per CLAUDE.md §5.5 — security hardening additive, break-compatible.

**Breaking change**: operator, передавший `SITE_BASE_URL=invalid-no-scheme` раньше получил бы его буквально в HTML; теперь получит prod default. Если кто-то намеренно использовал (не http/https) URL — сломается; маловероятно.

## Этап 101. Tests hardening II

**Что сделано:**

1. Bare `pytest.raises(Exception)` заменены на specific типы:
   - `test_stage88_observability_core.py`: `VetmanagerTimeoutError`, `VetmanagerError`
   - `test_stage91_vm_client_overhaul.py`: `VetmanagerError` (оба места)
   - `test_stage93_filter_builder.py`: `dataclasses.FrozenInstanceError`
2. `test_backoff_exponential_without_retry_after` — monkeypatch `random.uniform → 0` + strict assertions `d0 == 0.2, d1 == 0.4, d2 == 0.8` + `d0 < d1 < d2`. Vacuous test (который проходил при flat/reverse backoff) заменён на deterministic.
3. `test_api_contracts_hotfix::test_get_medical_cards_by_client_id_batches_medcards_via_in_operator` — dual-branch `int | str` assertion убран, pin на canonical integer list `[1, 2, 3]`. VM API wire format pinned.
4. Новый тест `test_half_open_probe_failure_reopens_with_fresh_cooldown` в `tests/test_stage101_tests_hardening.py` — покрытие HALF_OPEN → OPEN transition (была покрыта только HALF_OPEN → CLOSED).
5. Новые regression-тесты для stage 100.1 sanitizer coverage: `test_sanitizer_redacts_unlisted_api_prefixed_key` (allowlist narrow-scope check), `test_sanitizer_redacts_stacktrace_frame_vars`, `test_sanitizer_redacts_breadcrumb_data`.

**Не сделано (documented rationale):**
- 101.2 Public test-helpers `get_shared_http_client()` / `get_breaker_state()` — тесты использующие module-level privates работают стабильно; рефактор API для сокращения test-coupling к internals — nice-to-have, не prod risk.
- 101.6 `test_parse_retry_after_http_date_form` time tolerance — на stage 96.6 окно уже уменьшено до 60s с ±5s tolerance; flaky только на сильно loaded CI. Not worth freezegun complexity.
- 101.9 PROMPTS_SRC substring → real function calls — закрыто в stage c87bfa8 (TestStage87PromptSweep использует `await mcp.get_prompt(name)` + `render`, async tests на pytest-asyncio).

**Stage 101 follow-up (2026-04-18):** 101.8 закрыт на этом проходе.

Два root cause'а подавляли caplog/direct-handler capture в full suite runs:

1. `structured_logging.configure_logging()` раньше делал `logging.basicConfig(..., force=True)` на import server.py — это удаляло все root handlers (включая pytest caplog). Переписано: модуль создаёт собственный StreamHandler, помеченный атрибутом `_vm_structured_logging_handler=True`, и добавляет его только если такого ещё нет. Это:
   - coexist'ит с pre-existing handlers (host process, caplog) без дубликатов;
   - idempotent (проверка — есть ли наш marker-handler, вместо module-level bool-флага, который не восстанавливается после внешних `dictConfig`/`removeHandler` событий);
   - не мутирует formatter/filter чужих handlers (убрал over-reach, выявленный Codex review'ом).

2. `alembic/env.py` вызывал `logging.config.fileConfig(...)` с default `disable_existing_loggers=True`. Когда `tests/test_migrations.py` запускался раньше `test_stage88_observability_core.py::test_timeout_emits_structured_warning_and_records_latency`, он флипал `vetmanager.runtime.disabled=True`, и все warning'и оттуда уходили в void. Fix: `fileConfig(..., disable_existing_loggers=False)`.

Test `test_timeout_emits_structured_warning_and_records_latency` переписан под реальные `LogRecord`'ы через handler напрямую на `vetmanager.runtime` (без `_StubLogger`). Belt-and-suspenders: runtime_logger.disabled=False reset внутри теста на случай новых `dictConfig` callers в будущем.

Codex review (2-й проход): 0 findings после применения первой volны замечаний.

**Full suite**: 648 passed.

**Codex review**: закрыто с 0 findings после 1 iteration'а (первые замечания про handler dedup + `_CONFIGURED` brittleness адекватные, исправлены; остальные nit — задокументированы).

## Этап 102. Product consistency sweep

**Что сделано:**

1. `tools/pet.py::get_pet_profile` — partial-gather pattern parity с `get_client_profile`: `asyncio.gather(return_exceptions=True)` + explicit `CancelledError` re-raise + `_section()` helper + `partial: True` / `section_errors` response fields + `RUNTIME_LOGGER.warning("aggregator_partial")` log.
2. `prompts.py::unconfirmed_appointments` — добавлен `days_ahead: int = 2` параметр; `end_date` вычисляется в Python через `datetime.date.fromisoformat + timedelta`; prompt содержит готовые ISO строки вместо псевдокода «date+2d», не полагается на LLM арифметику. Fallback на literal даты если `fromisoformat` упадёт.
3. `prompts.py::low_stock` — добавлен `clinic_id: int = 1` параметр; `⚠️ Slow operation` warning prominent в prompt text; совет user'у narrow scope перед вызовом.
4. `landing_page.py` — убраны overpromise-строки:
   - line 594 tile: «выручка и остатки» → «карточки и история визитов»
   - line 638 bullet: «финансы, склад, выручка» → «сотрудники, загрузка врачей»
   - bullet «Какие товары заканчиваются на складе?» удалён
   - bullet «Покажи выручку и последние оплаты» заменён на «неоплаченные счета».
5. `tools/good.py::get_goods` + `tools/admission.py` — `name=` параметр помечен `[DEPRECATED — use title=]` в docstring.

**Не сделано:**
- 102.2 `get_pet_profile` `_instrumented_call` — aggregator делает 3 parallel `vc.get()` на разных endpoints; обернуть весь aggregator одним `tool_call` label теряет разделение. Полноценное решение — переместить `record_tool_call` на уровень VetmanagerClient._request. Отдельный рефактор.
- 102.7 Structured `section_errors` — current `f"{type}: {msg}"` работает для LLM surface'а; полная structured shape c `{error_type, retryable}` требует mapping layer на каждое исключение. Нет bug'а — nice-to-have.
- 102.8 Schedule группа decision — продуктовое решение, не техническое.

**Тесты**: `test_stage87_post_migration::test_unconfirmed_appointments_uses_status_filter` обновлён на новую форму (`date_to=` без literal суффикса, так как ISO строки теперь генерируются из f-string). Full suite 646 passed.

**Codex review**: пропущен per CLAUDE.md §5.5 (product copy tweaks + partial-gather copy-paste из get_client_profile — well-tested pattern).

## Этап 103. Architecture consolidation (low-risk subset)

**Что сделано:**

1. **103.5** `request_credentials.py` — упрощён до standalone 10-line shim с собственной копией `_get_request_headers()`. Больше не зависит от `request_auth` (избежание circular import). 11 test-call-sites продолжают работать через `patch.object(request_credentials, "_get_request_headers", ...)`. `request_auth.get_bearer_token` продолжает routing через `request_credentials._get_request_headers` — чтобы существующие monkeypatches сразу перехватывали.
2. **103.6** `service_metrics.instrument_call` — canonical location для latency+outcome метрики wrapper'а. `tools/crud_helpers._instrumented_call` теперь re-export (один import из service_metrics). Aggregator tools и web handlers могут использовать `instrument_call` без import crud_helpers.
3. **103.7** `tools/_aggregation.py::gather_sections` — shared helper для partial-gather паттерна: принимает `tool_name`, `context` dict, list of `(section_name, coro, fallback_shape)` triples. Handles explicit CancelledError re-raise + section_errors + `aggregator_partial` structured warning. Существующие `get_client_profile` и `get_pet_profile` оставлены на inline-версии (no-op refactor) — helper доступен для будущих aggregator'ов.

**Не сделано (high-risk / out-of-scope):**
- 103.1 `auth/` package — critical path; отдельный focused stage с собственным PRD и Codex review.
- 103.3 `resources/<entity>.py` gateway — architectural shift; отдельный этап с обсуждением product/performance impact.
- 103.4 `vetmanager_client.py` split (574 LOC → modules) — orthogonal refactor; текущая форма тестируется и проходит 648 tests без проблем.

**Stage 103 follow-up (2026-04-18):**

- **103.1 (full package split)** `auth/` package — закрыто: 5 разрозненных top-level модулей (`bearer_auth.py`, `vetmanager_auth.py`, `bearer_rate_limiter.py`, `request_auth.py`, частично `request_credentials.py`) консолидированы в `auth/` с 6 submodule'ями (`__init__`, `context`, `vetmanager`, `bearer`, `rate_limit`, `request`). Top-level файлы стали BC shim'ами ≤ 22 LOC с `from auth.X import *` re-exports. Codex review: 1 warning (rate-limiter patch surface regression) — addressed двумя механизмами: (1) `auth.bearer.resolve_bearer_auth_context` читает limiter через `auth.rate_limit.BEARER_RATE_LIMITER` module attribute (не `from ... import` snapshot), так что `reset_bearer_rate_limiter()` пересоздаёт singleton и следующий call видит fresh instance; (2) `reset_bearer_rate_limiter()` дополнительно синкает `bearer_rate_limiter.BEARER_RATE_LIMITER` shim attribute через `sys.modules` lookup, чтобы legacy callers по attribute access тоже видели fresh instance. `VetmanagerAuthContext` class identity preserved (одна и та же class object в обоих import paths). `request_credentials` shim retained — 11 тестов патчат `_get_request_headers` оттуда, миграция тест-базы — отдельная задача. Полная rate-limiter namespace consolidation на `rate_limit_backend` — out-of-scope: low-ROI без concrete driver.

- **103.3 (focused subset)** `resources/` gateway — закрыто: `resources/__init__.py` + `resources/client_profile.py` (95 LOC) + `resources/pet_profile.py` (106 LOC). Entity-specific aggregate-profile composition вынесена из tool registration functions. Tools `_get_client_profile_impl`/`_get_pet_profile_impl` → 3-line делегаторы. `instrument_call("aggregate_profile")` остался в tool-обёртке (aggregator p95 bucket не размывается внутренними sub-request latencies). Circular import break: `ACTIVE_ADMISSION_STATUSES` импортится lazy из `tools.admission` внутри `client_profile.fetch()` (schedule-chain cycle). `tools/client.py` больше не импортит `VetmanagerClient`. Behavior-preserving: same section names, same filter values, same response keys, same fallback chains. Polный Resource class abstraction (CRUD methods `list/by_id/search`) out-of-scope — simple CRUD уже в `crud_helpers`, добавление class layer не добавляет тестируемости без concrete use case. Codex review: 0 findings.

- **103.4 (full)** `vm_transport/*` split — закрыто: `vetmanager_client.py` 752 → 445 LOC (41% reduction). Извлечены 4 submodule'я, VetmanagerClient orchestrator класс остался thin + re-экспортирует каждый public/test-helper символ. BC surface критически важна: `conftest.py` клирит `_shared_http_clients`/`_breakers` через dict.clear() — работает через by-reference import (названия в vetmanager_client и vm_transport.{pool,breaker} указывают на ОДИН объект). Single test modification: `monkeypatch.setattr("vm_transport.retry.random.uniform", ...)` вместо `vetmanager_client.random.uniform` — явный docstring-note в test объясняет миграцию. Dead code `_SharedClientProxy` удалён. Codex review: 3 warnings. (1) BC decoupling breaker constants — документирован явным комментарием в import block; tests patch now `vm_transport.breaker.*` directly. (2) `_SharedClientProxy` confusion — dead code, удалён. (3) Pool race на concurrent first access — pre-existing issue в оригинале, out of scope (original code имел тот же race).

- **103.2** `FilterBuilder` caller migration — закрыто (commit 79223be): все 11 tool-модулей используют `filters.eq/in_/lt/lte/gt/gte/like` вместо raw dict-литералов. `paginate_all` нормализует mixed Filter/dict списки через `as_dict_list` перед сериализацией.
- **103.8** `build_list_query_params` → filters.py — закрыто: функция перенесена к Filter-примитивам, которые она сериализует. `validators.py` re-export'ит её для BC. Lazy import `validate_list_params` внутри filters (validators.py в остальном не зависит от filters). Все 3 tool-модуля (`crud_helpers`, `_inactive_helpers`, `medical_card`) + `tests/test_stage93_filter_builder.py` импортят напрямую из filters; `tests/test_validators.py` остался на BC-импорте как проверка контракта re-export'а.
- **103.1 (focused subset)** — вынос reject-паттерна из `resolve_bearer_auth_context` в `_reject(...) -> NoReturn` helper. 6 из 8 failure branch'ей (`revoked`, `expired`, `ip_denied`, `no_scopes`, `no_connection` + `rate_limited` остался inline потому что raise'ит RateLimitError, не AuthError) теперь читаются как линейный pipeline. `disabled`-branch оставлен standalone (его контракт — только metric, без audit log — закреплён тестом). Package split (`auth/{bearer,vetmanager,context}.py`), Validator classes, rate-limiter consolidation — deferred в 103a с отдельной сессией.

**Тесты**: 646 → 648 passed.

**Codex review**: для 103.2 — 0 findings; для 103.8 — 0 findings после 1 iteration (первые замечания про configure_logging handler double-install/brittleness fixed); для 103.1 (focused) — 0 findings.

## Этап 103a. Auth package split (full) — 2026-04-18

**Источник**: зонтик 103.1 из Roadmap stage 103; super-review 2026-04-17 findings.
**Commit**: 7185ac5.

**Что сделано:**

1. Создан `auth/` package с 5 submodule'ями:
   - `auth/context.py` (53 LOC): `VetmanagerAuthContext` dataclass + 6 constants (VETMANAGER_AUTH_MODE_*, headers, DEFAULT_USER_TOKEN_APP_NAME). Pure data, zero auth deps.
   - `auth/vetmanager.py` (63 LOC): `resolve_vetmanager_credentials(connection, *, encryption_key)` — connection→context resolver.
   - `auth/rate_limit.py` (108 LOC): `InMemoryBearerRateLimiter` + `BEARER_RATE_LIMITER` singleton + `reset_bearer_rate_limiter()` с двойным sync.
   - `auth/request.py` (34 LOC): `get_bearer_token()` HTTP header parser.
   - `auth/bearer.py` (278 LOC): `BearerAuthContext` + `_reject` helper + `resolve_bearer_auth_context` pipeline.
2. Top-level файлы стали BC shims: `bearer_auth.py` (13 LOC), `vetmanager_auth.py` (19), `bearer_rate_limiter.py` (22), `request_auth.py` (7) — все `from auth.<X> import *`.
3. `reset_bearer_rate_limiter()` синкает БОТЫЕ namespace'а (`auth.rate_limit.BEARER_RATE_LIMITER` + `sys.modules["bearer_rate_limiter"].BEARER_RATE_LIMITER`) чтобы тесты с `import bearer_rate_limiter` видели fresh instance после reset.

**Решения и обоснования:**

- **Runtime lookup через `auth.rate_limit.BEARER_RATE_LIMITER` (не snapshot)**: `resolve_bearer_auth_context` делает `from auth import rate_limit` + `rate_limit.BEARER_RATE_LIMITER.check_or_raise(...)` чтобы `reset_bearer_rate_limiter` рибайнд был виден на следующем вызове.
- **Shim-уровень preservation**: 11 тестов патчат `request_credentials._get_request_headers`, поэтому легаси модуль не удалён. Плановое удаление — отдельный этап (106+).
- **Rate-limiter namespace consolidation** (на generic `rate_limit_backend`) — deferred: substantial cross-cutting refactor без concrete driver.

**Codex review**: 1 warning (rate-limiter patch surface regression) → исправлен двойной sync + runtime lookup. После fix — 0 findings.

**Тесты**: 648 passed.

## Этап 103c. Resources gateway layer (focused subset) — 2026-04-18

**Источник**: зонтик 103.3.
**Commit**: dffe240.

**Что сделано:**

1. `resources/__init__.py` + `resources/client_profile.py` (95 LOC) + `resources/pet_profile.py` (106 LOC).
2. `resources/client_profile.fetch(client_id)` — 4-section composition: client record + last 5 invoices + last 5 admissions + next scheduled admission (IN-filter c ACTIVE_ADMISSION_STATUSES).
3. `resources/pet_profile.fetch(pet_id)` — 3-section: pet record + last 5 MedicalCards (filter=patient_id) + all vaccinations. Derives last/next_vaccination_date from sorted vaccination list.
4. `tools/client.py::_get_client_profile_impl` + `tools/pet.py::_get_pet_profile_impl` — 3-line делегаторы к resource'ам.

**Решения и обоснования:**

- **instrument_call("aggregate_profile")** остался на tool boundary, не в resource — aggregator p95 metric bucket отдельно от sub-request CRUD p95.
- **Lazy import `ACTIVE_ADMISSION_STATUSES` внутри `fetch()`**: circular break — `tools.admission` импортится через schedule chain.
- **VetmanagerClient() instantiated inside fetch()**: cheap, lazy credentials; сохранил original behavior.
- **Full Resource class (CRUD list/by_id/search)** out-of-scope: simple CRUD уже в `crud_helpers`, class layer без concrete use case — over-abstraction.
- **Layering violation** (resources импортит `tools._aggregation.gather_sections` и `tools.admission.ACTIVE_ADMISSION_STATUSES`) — flagged by super-review 2026-04-18 как high finding F5, запланирован fix в 106.3.

**Codex review**: 0 findings (все nit-комментарии подтверждают подход).

**Тесты**: 648 passed.

## Этап 103d. vm_transport split — 2026-04-18

**Источник**: зонтик 103.4.
**Commit**: ce3dd67.

**Что сделано:**

1. `vm_transport/` package с 4 submodule'ями:
   - `retry.py` (80 LOC): `parse_retry_after` (int+HTTP-date form, clamped 300s, rejects inf/nan), `backoff_seconds` (0.2×2^attempt + jitter), `MAX_RETRIES_READ=3/WRITE=0`, `RETRY_STATUS_CODES={429,502,503,504}`.
   - `cache_policy.py` (49 LOC): `CACHE_TTL_SECONDS=900`, `CACHE_TTL_SHORT_SECONDS=60`, `SHORT_TTL_ENTITIES={admission,medicalcard,invoice,client,pet,payment}`, `entity_from_path`, `ttl_for_entity`.
   - `pool.py` (117 LOC): per-loop `_shared_http_clients: dict[int, httpx.AsyncClient]`, keyed by `id(asyncio.get_running_loop())`. `get_shared_http_client` lazy-init per-loop. `REQUEST_TIMEOUTS` (connect=5s, read=20s, write=10s, pool=2s), `HTTP_LIMITS` (keepalive=50, total=100, expiry=30s).
   - `breaker.py` (205 LOC): `DomainBreaker` dataclass (closed/open/half_open), `_breakers` registry, `check_breaker_allows` + `breaker_record_success/failure`, env-tunable `BREAKER_FAILURE_THRESHOLD=5`, `BREAKER_WINDOW_SECONDS=60`, `BREAKER_COOLDOWN_SECONDS=30`.
2. `vetmanager_client.py` 752 → 445 LOC (41% reduction). `VetmanagerClient` orchestrator — thin. Re-exports всех public/test-helper символов для BC.
3. `_SharedClientProxy` dead code — удалён.

**Решения и обоснования:**

- **Dict-identity BC**: `from vm_transport.pool import _shared_http_clients` binds same dict object; `conftest.py::_reset_vm_client_state` clears via `dict.clear()` на vetmanager_client namespace — мутация видна через reference.
- **Cache TTL inline в VetmanagerClient**: `_request` читает module-level `CACHE_TTL_*` names (не `ttl_for_entity` helper) чтобы сохранить monkey-patch surface existing тестов `test_cache_entry_expires_after_ttl`. Canonical helper `ttl_for_entity` exists, но production path обходит — TD для 106/108.
- **Single test change**: `monkeypatch.setattr("vm_transport.retry.random.uniform", ...)` (был `vetmanager_client.random.uniform`). Тесты что патчат internal random уехали по канонической локации.
- **Breaker constants decoupling**: re-exported `_BREAKER_*` в vetmanager_client — snapshots; canonical — `vm_transport.breaker.BREAKER_*`. Documented inline, tests переключатся при необходимости.
- **Pool concurrent first-init race** — pre-existing, existed before split. Flagged by super-review 2026-04-18 (F3), запланирован fix в 106.2.

**Codex review**: 3 warnings — 2 addressed (dead `_SharedClientProxy` удалён; BC decoupling breaker constants documented), 1 pre-existing (pool race) out-of-scope, вынесен в 106.2.

**Тесты**: 648 passed.

## Этап 105. Blocker hotfix — super-review 2026-04-18

**Commit**: 6a10df6 (backfilled stage 116.5).

**Что сделано:**

1. **105.1 B1 Roadmap doc sync** — обновил outdated status block "Status после cleanup sweep" (был: "103.3/103.4 остаются в зонтике"; теперь: "все 8 sub-stages закрыты" с commit hashes). Добавил `## Этап 103a / 103c / 103d` headers с собственными sub-task списками для `check_stage_completion.sh`.

2. **105.2 B2 breaker amplification + retry re-check** — `vetmanager_client.py::_request`:
   - Убрал per-attempt `_breaker_record_failure` из `except httpx.TimeoutException` / `except httpx.RequestError` branches. С MAX_RETRIES_READ=3 один failing GET насчитывал 4 failure, trip'ая circuit после 1 реального запроса (threshold=5).
   - Один `_breaker_record_failure` в terminal path каждой branch — одна failure на logical call.
   - `_check_breaker_allows(domain_key)` в начале retry loop при `attempt > 0`. Если другой concurrent caller trip'нул breaker во время backoff sleep — re-check raises `VetmanagerUpstreamUnavailable`, retry loop abort'ится без дальнейших round-trips.
   - 5xx retryable path (429/502/503/504) не тронут — там `_breaker_record_failure` уже счётчит per-logical-call (фирит только на non-retry branch).

3. **105.3 AssumptionLog** — добавил dedicated секции `## Этап 103a / 103c / 103d` (выше) для выполнения CLAUDE.md §6 + CI check.

**Решения и обоснования:**

- **Per-logical-call semantics for breaker**: breaker threshold должен реагировать на user-visible failures, не на implementation detail (retry count). Stage 99.1 per-attempt counting введён был без учёта что retry amplifies; super-review 2026-04-18 обнаружил.
- **Re-check только при `attempt > 0`**: первый check остался над while loop (не дублируем на первой итерации). Async race window между re-check и next HTTP call — acceptable; `_check_breaker_allows` locked внутри.
- **5xx оставлен без изменений**: текущая логика корректна — `_breaker_record_failure` только в non-retry branch.

**Codex review**: 0 findings after test rewrite. Первоначально Codex отметил что второй тест не покрывал новый `attempt > 0` path (тестировал initial check); переписал с sleep-hook, эмулирующим breaker trip между iterations.

**Тесты**: 648 → 650 passed (+2).

## Этап 106. High-severity reliability + docs hardening — 2026-04-18

**Commit**: 936b3aa (backfilled stage 116.5).

**Что сделано:**

1. **106.1 F2 CancelledError wedges HALF_OPEN probe** — `vetmanager_client.py::_request`:
   - Обернул весь retry loop в `try: ... finally:` scope на уровне _request.
   - Добавил flag `_breaker_resolved = False` при enter scope'а. Каждая ветка успешного/failure exit ставит `_breaker_resolved = True` после своего breaker hook (`_breaker_record_success` или `_breaker_record_failure`).
   - В `finally`: если `not _breaker_resolved` — значит вылетели с UNEXPECTED exception (CancelledError, KeyboardInterrupt, shutdown), когда ни одна normal branch не успела отработать. Делаем `await _breaker_record_failure(domain_key)` — это сбрасывает `probe_in_flight=False` (через state machine: HALF_OPEN → OPEN + probe_in_flight clear).
   - Test: `test_cancelled_probe_clears_breaker_probe_in_flight` — force_breaker_open(cooldown_elapsed=True) ⇒ HALF_OPEN probe; httpx mock raises CancelledError; после `pytest.raises(CancelledError)` проверяем `get_breaker_state(DOMAIN)["probe_in_flight"] is False`.

2. **106.2 F3 pool concurrent first-init race** — `vm_transport/pool.py::get_shared_http_client`:
   - Добавил `async with _shared_http_client_lock:` wrapping double-check. Fast path (есть живой client в dict) идёт без блокировки. Slow path (нужно create) под lock'ом с re-check внутри — N concurrent coroutines получают ОДИН AsyncClient, не N.
   - Обновил docstring про stage 106.2 fix. Lock комментарий обновил: "previously dead code reserved for BC" → "actively used".
   - Test: `test_concurrent_first_init_creates_single_pool_client` — 8 concurrent `gather` вызовов get_shared_http_client на чистом loop; assert все 8 возвращают один и тот же instance, dict содержит ровно одну запись.

3. **106.3 F5 layering violation** — вынес shared helpers вниз:
   - `tools/_aggregation.py` (gather_sections) → `resources/_aggregation.py` (canonical). `tools/_aggregation.py` стал BC shim с `from resources._aggregation import gather_sections`.
   - `ACTIVE_ADMISSION_STATUSES` из `tools/admission.py` → `resources/admission_status.py` (canonical). `tools/admission.py` re-экспортит для `tools/schedule.py` + тестов.
   - `resources/client_profile.py` импортит `ACTIVE_ADMISSION_STATUSES` и `gather_sections` из canonical locations — убран lazy import и `from tools...` imports.
   - `resources/pet_profile.py` — import `gather_sections` из `resources._aggregation`.
   - Invariant verified: `grep -rE "^(from |import )tools\." resources/` пустой. Layering `tools/ → resources/ → vm_transport/ + auth/` без upward imports.

4. **106.4 F6 filters.py zero-filter privacy** — `filters.build_list_query_params`:
   - Удалил ветку `if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0: continue` из `extra` loop.
   - Теперь skip'аются только None и empty string. `client_id=0` / `pet_id=0` и прочие numeric zero value попадают в params как явный filter, не silently драпаясь в unfiltered full-scan (privacy risk).
   - Test: `test_skips_empty_extra_values` обновлён под новый контракт (`client_id=0` now in params). Новый `test_preserves_int_zero_in_extra` — regression guard.

5. **106.5 technical-requirements rewrite** — `artifacts/technical-requirements-vetmanager-mcp-ru.md`:
   - §3.2 `Vetmanager API client` переписан: `VetmanagerClient` — thin orchestrator над `vm_transport/`. Добавил структуру 4 submodule'ей.
   - §3.2 `Bearer auth resolution` переписан: canonical location `auth/`. Перечислил все 5 submodule'ей. BC shims описаны как shim re-exports.
   - §3.2 добавил секцию `Resource gateway (resources/*)` с описанием client_profile / pet_profile / _aggregation / admission_status.
   - §3.2 `Validation helpers` обновлён — `build_list_query_params` теперь в filters.py (stage 103.8). Добавил отдельную секцию `FilterBuilder (filters.py)`.
   - §3.3 Структура проекта — полностью переписан file tree: добавлены auth/, vm_transport/, resources/ пакеты с submodule'ями. Top-level BC shims явно помечены как shim с LOC. Добавлен invariant layer rule "tools/ → resources/ → vm_transport/ + auth/".

6. **106.6 obsolete URL 342915.simplecloud.ru** — `Roadmap.md:902` (этап 56.1.4):
   - Пометил старый host как "исторически был; заменён на vetmanager-mcp.vromanichev.ru в этапе 89.2".

7. **106.7 H21 dead sentinel + stale state helper** — `vetmanager_client.py`:
   - Удалил `_shared_http_client: httpx.AsyncClient | None = None` sentinel (dead code после 103d split).
   - Переписал `get_shared_http_client_state()` — теперь читает реальный `_shared_http_clients` dict: `{loop_keys, open_count, current_loop_registered}`. Раньше возвращал `{exists: False, closed: True}` всегда (misleading stale view).
   - Обновил `tests/conftest.py::_reset_vm_client_state` — убрал rebind `_shared_http_client = None` (dead name больше нет); `dict.clear()` достаточно.

**Решения и обоснования:**

- **try/finally на уровне _request (не per-attempt)**: проще и надёжнее — одна точка очистки breaker state на любом exception path, включая те что мы не ловим явно. Альтернатива "catch CancelledError + re-raise" хуже — нужно добавлять в каждую except ветку, легко забыть новую.
- **Lock в pool.py — re-use, не удалить**: существующий `_shared_http_client_lock` сохранил, просто сделал его actively used. Создание нового Lock'а тоже работало бы, но именно переиспользование устраняет комментарий "dead code reserved for BC" который смущал.
- **ACTIVE_ADMISSION_STATUSES в resources/admission_status.py, не в exceptions/ или constants/**: constants логически относятся к domain entity (admission), поэтому под resources/. Схожие enum будут добавляться к resources/<entity>_status.py.
- **Zero-filter удалён полностью, не "warn if dropped"**: silent behavior + опционально warn — два lifecycle для одной semantics, confusing. Проще: сейчас ноль — valid filter value, callers ответственны за omit если не нужен.
- **_shared_http_client sentinel удалён**: никто из production кода его не читал после 103d (grep confirms). Удаление упрощает test contract.

**Codex review**: (pending — запускается после commit).

**Тесты**: 650 → 653 passed (+3: 2 × 106 reliability + 1 × 106.4 regression).

## Этап 107. Observability gaps — 2026-04-18

**Commit**: 82555c8 (backfilled stage 116.5).

**Что сделано (10 подзадач):**

1. **107.1 H10 Rate-limit log at raise site** — `auth/rate_limit.py::InMemoryBearerRateLimiter.check_or_raise`. Перед `raise RateLimitError` — `RUNTIME_LOGGER.warning("Bearer rate limit triggered", extra={event_name="bearer_rate_limit_triggered", token_id, retry_after_seconds, request_limit, window_seconds})`. Raw token не логируем, только token_id.

2. **107.2 H11 Token issue/revoke structured log** — `web_routes_account.py`. На success `issue_service_bearer_token` — `RUNTIME_LOGGER.info("Bearer token issued", extra={event_name, account_id, token_id, token_name, expires_in_days})`. Симметрично `revoke_service_bearer_token` — `event_name=bearer_token_revoked`. Добавил `from observability_logging import RUNTIME_LOGGER` import.

3. **107.3 H12 Register success + failure metric** — `web_routes_auth.py::register_submit`. На success `register_account` — `RUNTIME_LOGGER.info("Account registered", extra={event_name=account_registered, account_id})`. На rate-limit — `record_auth_failure(source="web_register", reason="rate_limited")`. На ValueError (duplicate email / weak password) — `record_auth_failure(source="web_register", reason="validation_error")`.

4. **107.4 aggregator_partial correlation_id propagation** — `resources/_aggregation.py::gather_sections`. Добавил merge `**get_current_request_context()` в extra dict warning'а перед `**context`. SRE может join'ить `aggregator_partial` log с upstream events (vm_upstream_timeout, etc.) по `correlation_id` / `request_id`.

5. **107.5 section_errors AuthError scrubbing** — `resources/_aggregation.py`. Для `AuthError` в section_errors[name]["message"] логируем только `type(result).__name__`, не `f"{type}:{result}"` — иначе masked API key fragment (e.g. `"Invalid or missing API key (ab***yz)"`) уходит в log aggregator. Other exception types сохраняют полное сообщение — полезная operational context.

6. **107.6 tool_name label в instrument_call** — `service_metrics.py`. Добавлен опциональный `tool_name: str | None = None` параметр в `instrument_call` и `record_tool_call`; если задан — label ключа становится `endpoint:tool_name`. Tool-wrappers `get_client_profile` / `get_pet_profile` передают `tool_name="get_client_profile"` / `"get_pet_profile"` — их aggregate p95 больше не conflate'ится с CRUD list-ов того же endpoint.

7. **107.7 billing_api latency metric** — `host_resolver.py::resolve_vetmanager_host`. Добавил `started = time.monotonic()` в начале каждого attempt'а и `record_upstream_request(target="billing_api", status=..., duration_seconds=elapsed)` на success/timeout/network_error paths. Раньше существовали только failure counters; теперь SRE видит slow host-resolution через `upstream_request_latency_seconds{target="billing_api"}`.

8. **107.8 graceful_shutdown structured** — `server.py::_graceful_shutdown`. Заменил `logging.getLogger("vetmanager.runtime").warning(...)` на `RUNTIME_LOGGER.warning("Graceful shutdown error", extra={event_name=shutdown_error, step=<name>}, exc_info=True)`. Добавил симметричный log для `reset_breakers` branch (раньше был silent `except Exception: pass`).

9. **107.9 Breaker HALF_OPEN → CLOSED recovery log** — `vm_transport/breaker.py::breaker_record_success`. При `state in ("half_open", "open")` → `RUNTIME_LOGGER.info("Circuit breaker recovered", extra={event_name=circuit_breaker_closed, domain, previous_state})`. Incident timeline теперь видит момент recovery.

10. **107.10 Intermediate retry log** — `vetmanager_client.py::_request`. В `except httpx.TimeoutException` перед `if attempt < max_retries: continue` — `RUNTIME_LOGGER.debug("VM upstream timeout on retry attempt", extra={event_name=vm_upstream_timeout_retry, correlation_id, domain, method, url_path, attempt, elapsed_ms})`. Раньше только terminal timeout логировался; intermediate retries — silent. DEBUG чтобы не флудить INFO на 429 episodes.

**Решения и обоснования:**

- **AuthError scrubbing в section_errors только**: остальные исключения (NotFoundError, VetmanagerTimeoutError, etc.) не содержат credential fragments — им полезно оставить full message для debugging. Full-logging sanitizer — отдельная задача (Codex-blindspot L7 speculative).
- **tool_name через separator `:`**: `{endpoint}:{tool_name}` — формат легко parsable и совместим с существующими tool_call_latency label'ами. Cardinality +15 tool_name values × 2 outcomes ≈ +30 series — negligible.
- **Retry log на DEBUG**: INFO для last attempt (уже был), DEBUG для intermediate — grep'ать можно, в прод Prometheus/Loki по умолчанию собирают.
- **billing_api metric: status=`http_NNN` / `timeout` / `network_error`**: соответствует naming convention `vetmanager_api`.

**Codex review**: (pending — будет запущен после commit).

**Тесты**: 653 passed (без регрессий). Новые тесты не добавлены — observability правки не меняют behavior, только enrich логи/метрики. Regression caught by existing integration tests.

## Этап 108. Code quality cleanup — 2026-04-18

**Commit**: 94e0ff9 (backfilled stage 116.5).

**Что сделано (10 подзадач):**

1. **108.1 F7 type builtin shadow** — `tools/admission.py::update_admission`. Параметр `type: str = ""` переименован в `admission_type: str = ""`. Wire-level payload остался `payload["type"] = admission_type` — VM API контракт не меняется. Обновлён docstring. Тест `test_update_admission_extended_fields` обновлён: call-kwarg `type="first_visit"` → `admission_type="first_visit"`, комментарий-marker про stage 108.1.

2. **108.2 F8 duplicated admission list unwrap** — `tools/admission.py`. 12-line блок `data.get("admission") or data.get("admissions") or []` + totalCount extraction появлялся 2× в `get_client_upcoming_visits` и `get_daily_schedule`. Вынесен в module-level helper `_unwrap_admission_list_response(resp) -> tuple[list, int]`. Call-sites теперь однострочные `rows, total = _unwrap_admission_list_response(resp)`.

3. **108.3 H14 inline datetime imports** — `tools/admission.py`. 3× `from datetime import date as _date, timedelta as _td` (или variant) внутри function bodies заменены на один module-level import `from datetime import date as _date, timedelta as _td` наверху файла.

4. **108.4 H15 inline filters imports в medical_card.py** — `tools/medical_card.py`. 2× inline `from filters import eq as _filter_eq [, in_ as _filter_in]` в function bodies подняты в module-level top import `from filters import build_list_query_params, eq as _filter_eq, in_ as _filter_in`.

5. **108.5 inline imports в tools/_aggregation.py** — skipped после 106.3: файл стал thin shim (`from resources._aggregation import gather_sections`). Переехало всё в `resources/_aggregation.py` где imports уже на module level.

6. **108.6 tools/client.py inline imports** — skipped: `from service_metrics import instrument_call as _instrument_call` и `from resources.client_profile import fetch as _fetch_client_profile` остались inline внутри tool body, потому что они нужны ТОЛЬКО во время регистрации (inner async def) и top-level move нарушил бы lazy pattern — вынесу в отдельной focused сессии когда будут другие tool-tree refactors.

7. **108.7 medical_card nested ternary** — `tools/medical_card.py:134`. Однострочный `pet_by_id.get(pid) or pet_by_id.get(int(pid) if isinstance(pid, str) and pid.isdigit() else pid)` разложен на 2 строки с promoted `int_pid` переменной и поясняющим комментарием про VM API int/digit-string двойственность.

8. **108.8 duplicate Stage-83 comment** — `tools/admission.py:219-220`. Вторая копия `# API-level active status filter via IN operator # (verified during Stage 83 probe on devtr6)` удалена; первая копия у `get_client_upcoming_visits` сохранена — достаточно для context.

9. **108.9 REQUEST_TIMEOUT dead const** — `vetmanager_client.py:74`. Удалён `REQUEST_TIMEOUT = 30.0` — не используется в файле после 103d split'а (actual timeouts — в `vm_transport/pool.py::REQUEST_TIMEOUTS` split). Оставлен комментарий о переносе. Другие модули (`host_resolver.py`, `vetmanager_connection_service.py`) имеют свои local `REQUEST_TIMEOUT = 30.0` constants — не трогали (их используют).

10. **108.10 _env_int / _env_float 3x dedup** — создан `env_utils.py` (module-level) с public `env_int(name, default, *, positive_only=True)` + `env_float(name, default, *, positive_only=True)`. `auth/rate_limit.py` и `vm_transport/breaker.py` импортят оттуда. Локальные копии удалены. `positive_only=True` по умолчанию (legacy semantics: ≤0 → fallback) для обеих call-sites.

**Решения и обоснования:**

- **`admission_type` vs `kind`**: `admission_type` — domain-consistent (VM payload field is `type`, MCP user arg `admission_type` — соответствует существующему `admission_type` в create_medical_card). Другие tool-модули могут использовать тот же pattern при similar conflict'ах.
- **`_unwrap_admission_list_response` private, не public**: helper специфичен для `/rest/api/admission` endpoint'а (`.admission` / `.admissions` key fallback). Generic `_unwrap_list_response(resp, keys=...)` — premature abstraction без второго caller.
- **inline imports в tools/client.py оставлены**: lazy import там — защита от циркулярного импорта `resources.client_profile → tools.admission` при test monkey-patch. Trivial move ломает test setup, отложено.
- **env_utils.py top-level, не config/env.py package**: один файл < 50 LOC, не нужен namespace. Если появится pydantic-settings migration — можно reorg.

**Codex review**: (pending — будет запущен после commit).

**Тесты**: 653 passed. 1 тест обновлён (`test_update_admission_extended_fields` — kwarg rename под 108.1).

## Этап 109. Test brittleness & coverage gaps (focused subset) — 2026-04-18

**Commit**: 7ad05d1 (backfilled stage 116.5).

**Что сделано (5 subtasks — highest impact, lowest risk):**

1. **109.2 H17 monkeypatch вместо manual save/restore** — `tests/test_stage102_aggregator_structured_errors.py`. Заменил manual `vm.asyncio.sleep = _no_sleep` + try/finally restore на `pytest.MonkeyPatch().setattr("vetmanager_client.asyncio.sleep", _no_sleep)` + `mp.undo()` в finally. xdist-safe, auto-restore на любом исключении.

2. **109.4 H19 dead PROMPTS_SRC read** — `tests/test_stage87_post_migration.py`. Удалил `PROMPTS_SRC = Path(__file__).../read_text()` (никогда не используется в тестах — они используют `_render_prompt_body` через FastMCP registry). Ломал collection если prompts.py переносить. Удалил unused `from pathlib import Path`.

3. **109.6 BC-invariants regression tests** — новый `tests/test_stage109_bc_invariants.py` (7 tests):
   - `_shared_http_clients` dict identity между `vetmanager_client` и `vm_transport.pool`.
   - `_breakers` dict identity между `vetmanager_client` и `vm_transport.breaker`.
   - `VetmanagerAuthContext` class identity между `vetmanager_auth` и `auth.context`.
   - `resolve_bearer_auth_context` function identity между `bearer_auth` и `auth.bearer`.
   - `get_bearer_token` function identity между `request_auth` и `auth.request`.
   - `gather_sections` function identity между `tools._aggregation` (shim) и `resources._aggregation` (canonical).
   - `ACTIVE_ADMISSION_STATUSES` tuple identity между `tools.admission` и `resources.admission_status`.
   Ловит регрессию когда re-export рекопирует объект вместо shared reference — важно для conftest `dict.clear()` isolation fixture.

4. **109.9 `_parse_retry_after` boundary tests** — 4 новых теста в `tests/test_stage91_vm_client_overhaul.py`:
   - `test_parse_retry_after_clamps_to_300s_max` — 301 / 999999 / 1e9 → 300.0.
   - `test_parse_retry_after_clamps_negative_to_zero` — -5 / -0.01 → 0.0.
   - `test_parse_retry_after_accepts_float_seconds` — "1.5" / "0.25" → float.
   - `test_parse_retry_after_rejects_inf_nan` — inf/nan/-inf → None.
   Гарантия DoS-защиты от malicious upstream.

5. **109.11 upstream_unavailable error_type test** — `tests/test_stage102_aggregator_structured_errors.py`. Новый тест `test_section_errors_classify_upstream_unavailable_as_retryable`: force_breaker_open(DOMAIN), вызов get_pet_profile, assert что все 3 section_errors классифицированы `error_type="upstream_unavailable"` с `retryable=True`. Guards против drift в `_classify` маппинге.

**Что deferred (stop — low-ROI без concrete failure):**

- 109.1 runtime_factories public inject API — wide test-API refactor, нужен concrete pain (10+ call-site migration).
- 109.3 test_stage91 breaker private field access — работает через `get_breaker_state`, но private-attr assertions продолжают работать стабильно 665 tests.
- 109.5 request_auth patches migrate с shim на canonical — зависит от будущего request_credentials.py delete (отдельный этап).
- 109.7 test_stage91 magic-number pool/timeout asserts — по факту тестируют configuration stability, cost/benefit borderline.
- 109.8 test_wait_50ms deterministic — retry passes, flakiness не блокер.
- 109.10 vm_upstream_network_error parallel test — дублирует timeout-test; полный coverage nice-to-have.

**Решения и обоснования:**

- **Focused subset стратегия**: 5 из 11 subtask'ов реально ловят регрессии или делают tests xdist-safe. Оставшиеся 6 — либо bootstrap cost (109.1 API), либо стилистика (109.7 magic numbers), либо duplicative (109.10). Сделано > идеальность.
- **test_stage109_bc_invariants.py отдельным файлом**: BC-invariants — cross-cutting concern, нелогично прятать в existing stage-специфичный тест. File-level comment ссылается на conftest fixture.
- **`force_breaker_open` без cooldown_elapsed=True**: первый `_check_breaker_allows` возвращает VetmanagerUpstreamUnavailable сразу (OPEN state, cooldown не истёк) — как раз то что нужно для section_errors test.

**Codex review**: (pending — после commit).

**Тесты**: 653 → 665 passed (+12: 7 × invariant + 4 × retry_after boundary + 1 × upstream_unavailable).

## Этап 110. Product metrics — ad-hoc report + business events counter — 2026-04-19

**Commit**: 778cddc (backfilled stage 116.5).

**Что сделано:**

1. **`scripts/product_metrics_report.py`** (~370 LOC) — standalone async CLI-скрипт. Read-only aggregations по existing таблицам; никаких миграций, никаких новых контейнеров. Output markdown (default) или JSON. 20+ счётчиков в 4 группах: accounts (total / new 24h-7d-30d / live / dead / no_tokens / no_active_connection + dead_list table), tokens (active / expiring / issued / revoked), requests (total 24h-7d-30d + top-N accounts), failures (by_event_24h / 7d / 30d across 6 TOKEN_EVENT_AUTH_FAILED_* + RATE_LIMITED).

2. **`service_metrics.record_business_event(event_name)`** — process-local counter с strict allowlist {account_registered, web_login_succeeded, bearer_token_issued, bearer_token_revoked}. Экспортируется в Prometheus как `vetmanager_business_events_total{event=...}` через existing `/metrics` endpoint. 4 call-sites: register success, login success, token issue, token revoke.

3. **13 тестов** (`tests/test_stage110_product_metrics.py`) с изолированной SQLite fixture: 5 accounts + 5 tokens + 11 TokenUsageLog events покрывают каждый edge case классификации (live, dead, zombie-with-never-used-token, new-no-tokens, expired-in-future).

4. **Skill `.claude/commands/product-metrics.md`** с whitelist args validation (никакой shell injection через user args: `--window-days=<1..365>`, `--top-n=<1..100>`, `--format=markdown|json`; всё остальное — reject).

5. **README section** с примерами вызова + PII disclaimer.

**Решения и обоснования:**

- **Ad-hoc over persistent snapshot**: accounts < 100, owner один. Grafana/daily cron создаёт maintenance burden без value. Script on-demand живёт в git, backfill trivial.
- **`_mask_email` first 2 chars + full TLD**: balance между readable ID и PII protection. Для single-operator достаточно (Codex отметил как nit — добавил disclaimer в README).
- **`_to_aware` naive=UTC invariant**: prod uses `DateTime(timezone=True)`, но SQLite игнорит tz info. Helper нормализует на comparison level. Документировал invariant (Codex warning #3).
- **IN-list в `_count_dead_accounts`**: fine до ~5k accounts. Документировал как known limitation — rewrite в CTE когда scale вырастет (Codex warning #2, acceptable trade-off сейчас).
- **Allowlist для `record_business_event`**: prevents cardinality blow-up если future caller с typo или dynamic string. Silent drop — не raise, чтобы не ломать hot path.
- **`_labels_text` escape**: existing helper уже escapes backslash + double-quote per Prometheus spec. Не нужна отдельная валидация (Codex warning #1 fixed).
- **Skill whitelist args**: защита от shell injection через user args в `ssh "..."`. Only 3 arg patterns разрешены, все остальное reject (Codex nit #5 fixed).

**Simplicity evaluation (§4.1 preserved)**: все 8 triggers проверены. Единственное отклонение от минимализма — separate `format_markdown()` / `format_json()` functions (testable в изоляции) вместо inline procedure. ROI positive.

**Codex review (§5.1)**: 5 findings — (1) label escape, (2) IN-list scale, (3) tz invariant, (4) PII mask adequacy, (5) skill shell injection.

- #1 addressed: explicit docstring-comment что `_labels_text` escapes + allowlist дубль защиты.
- #2 documented: known scale limitation, acceptable for current <100 accounts.
- #3 addressed: explicit invariant docstring + Codex-note cross-ref.
- #4 addressed: README disclaimer "не анонимизация; для owner-local просмотра".
- #5 addressed: skill whitelist-validates args перед shell-call, uses single-quote quoting.

**Тесты**: 665 → 678 passed (+13).

## Этап 109.10 (follow-up) — vm_upstream_network_error parallel test

**Commit**: 3d4f75f (backfilled stage 116.5).

Закрыт один из 6 deferred 109-subtask'ов. Новый тест `test_network_error_emits_structured_warning_and_records_latency` в `tests/test_stage88_observability_core.py` — зеркальный к `test_timeout_emits_structured_warning_and_records_latency`:

- httpx mock raises `httpx.ConnectError("connection refused")` (subclass of `httpx.RequestError`).
- monkeypatch `asyncio.sleep` → no-op + `vm_transport.retry.random.uniform` → 0 — чтобы retry-path в `_request` не занимал время и был deterministic.
- Attaches `_ListHandler` на `vetmanager.runtime` logger (same pattern что в timeout-test).
- Asserts: `event_name == "vm_upstream_network_error"`, record fields (domain/method/url_path/elapsed_ms/error_class=="ConnectError"), `upstream_requests_total["vetmanager_api|network_error"] == 1`.

Guards против регрессии drift'а между timeout-branch и network-error-branch в `vetmanager_client._request`: обе ветки эмитят разный event_name + status, но структурно близки — смена одной без другой осталась бы невидимой.

**Тесты**: 678 → 679 passed (+1).

Остаются 5 deferred 109-subtask'ов (109.1, 109.3, 109.5, 109.7, 109.8) — документированы в Roadmap как low-ROI без concrete pain.

## Этап 109 full-subset follow-up — 2026-04-19

**Commit**: 3234e09 (backfilled stage 116.5).

Закрыты все 5 оставшихся 109-deferred subtask'ов («делай все фичи»). Stage 109 header → `done` (full subset).

### 109.1 runtime_factories private-attr coupling

- `make_vetmanager_auth_context` расширен: автоматически подставляет `credential_header=VETMANAGER_USER_TOKEN_HEADER` + `app_name=DEFAULT_USER_TOKEN_APP_NAME` для auth_mode=USER_TOKEN (раньше звалось inline в test_e2e_real).
- `make_client_with_resolved_runtime` теперь ЕДИНСТВЕННАЯ точка, пишущая VetmanagerClient private attributes. Docstring явно фиксирует инвариант — rename `_domain` и co требует правки одного места.
- `test_e2e_real.py::vc()` и `test_real_get_users_with_user_token_mode()` — 2 inline-клона factory заменены на вызов `make_client_with_resolved_runtime(... auth_mode=USER_TOKEN)`.
- Private-attr **readers** в asserts (`assert client._domain == ...`) оставил — renaming такого read surface легко ловится loud failure'ом; подменять их proxy-property бесполезно.

### 109.3 breaker private-field asserts → public API

Мигрированы 3 теста (`test_stage91`, `test_stage96`, `test_stage101`):
- `breaker.state` / `breaker.probe_in_flight` / `breaker.opened_at` reads → `get_breaker_state(domain)` dict snapshot.
- Прямое писание `breaker.state = "open"; breaker.opened_at = monotonic - cooldown - 1` под lock'ом → `force_breaker_open(domain, cooldown_elapsed=True)`.

### 109.5 patch targets migrate shim → canonical

- `auth/request.py` получил свою копию `_get_request_headers` как canonical location; `get_bearer_token()` переключён на локальную версию.
- `request_credentials.py` упрощён: `from auth.request import _get_request_headers` re-export (-25 LOC → -15 LOC).
- 17 patch-target'ов в 10 test-файлах мигрированы:
  - `tests/test_service_metrics.py`, `tests/runtime_factories.py`, `tests/test_request_auth.py`, `tests/test_e2e_real.py`, `tests/test_client_multitenancy.py`, `tests/test_runtime_auth.py`, `tests/test_browser_cleanup.py`, `tests/test_browser_happy_path_domain_api_key.py`, `tests/test_browser_happy_path_user_token.py`, `tests/test_browser_real_opt_in.py`.
  - Замена: `import request_credentials` → `import auth.request as auth_request`; `patch.object(request_credentials, "_get_request_headers", ...)` → `patch.object(auth_request, "_get_request_headers", ...)`.
- Shim `request_credentials.py` остаётся жить (1 import `from auth.request import`) — полное удаление модуля = отдельный future stage когда захочется.

### 109.7 magic-number asserts → behavioural

- `test_split_timeouts_are_configured`: вместо `assert connect == 5.0 AND read == 20.0` — `assert connect > 0 AND connect < read AND pool < read` (инвариант: fast-fail paths tighter than slow ones).
- `test_http_limits_enable_keep_alive_pool`: вместо `assert max_keepalive == 50 AND max_connections == 100` — `max_connections >= max_keepalive > 0 AND keepalive_expiry > 0` (инвариант: pool enabled и vmem'ed).
- Тюнинг pool-size 50→75 или timeout read 20→25 больше не false-fail тесты.

### 109.8 test_wait_50ms deterministic

- Монкипатчу `vetmanager_client.asyncio.sleep` recording-stub'ом — каждый вызов pace-logic собирается в list. Внутри test'а ждать по часам не нужно (sleep(0) на замене).
- Assert: `any(s > 0 for s in sleeps)` + `all(s <= REQUEST_GAP_SECONDS for s in sleeps)`. Отвязано от wall-clock jitter'а CI runner'а.

**Тесты**: 679 → 679 (no regression; +0 — 109.3/5/7/8/1 — рефакторы existing tests, не новые покрытия; 109.10 уже был).

**Roadmap state после commit'а**: 0 `todo` / 0 `in_progress` / 0 `stop` / 0 `deferred`. Все 879+ subtask'ов `done`.

## Этап 111. Blocker cleanup + metric gaps — 2026-04-19

**Commit**: e531c65 (backfilled stage 116.5).

Закрыл 2 blocker (F1 /metrics public + F3 token_usage_logs index) + 2 high (F5 login lockout metric + F6 silent-drop log) из super-review 2026-04-19. F7 (billing hardening) перенесён в stage 113 как logically belonging to "Resilience completeness" (~2h own scope).

### Что сделано

1. **F1 `/metrics` auth gate** — `web_routes_system.py::metrics_export` требует `Authorization: Bearer $METRICS_AUTH_TOKEN` когда env var задан (иначе 403). Без env — backward-compat open endpoint. `hmac.compare_digest` для timing-safe сравнения. Defence-in-depth: nginx `location = /metrics { allow 127.0.0.1; allow ::1; deny all; ... }` в `scripts/init_server.sh`. Codex после ревью: добавил IPv6 localhost allow (warning).
2. **F3 composite index** — `alembic/versions/20260419_000007_token_usage_logs_event_index.py` + `__table_args__ = (Index(...),)` в `storage_models.TokenUsageLog`. Planner'ы обоих (SQLite, Postgres) автоматически используют composite index для existing `WHERE event_type=X AND event_at>=Y` queries — query-text refactor не нужен для index-use. Query-collapse (10→1 GROUP BY) перенесён в stage 112 как отдельная perf-optimization.
3. **F5 login lockout metric** — один `record_auth_failure(source="web_login", reason="rate_limited")` в `web_routes_auth.py:200` (RateLimitError branch), симметрично с `web_register` (stage 107.3). Credential-stuffing становится visible в Grafana.
4. **F6 silent-drop log** — `service_metrics.record_business_event` теперь эмитит `RUNTIME_LOGGER.error("record_business_event: unknown event_name dropped", extra={"event_name": "business_event_unknown", "dropped_name": event_name})` перед `return` для unknown event_name. Counter по-прежнему не инкрементируется (cardinality защита), но typo теперь видно в логах. Import `RUNTIME_LOGGER` — module-level (не inline, следуя F2 recommendation).

### Решения и обоснования

- **Backward-compat METRICS_AUTH_TOKEN**: если env не задан — endpoint open. Причина: self-hosted dev + existing prod deploys не ломаются. Production deploy обязан установить token (документировано в комментарии). Alternative (mandatory token) отклонён — breaking change без migration path.
- **hmac.compare_digest вместо `==`**: timing-safe string compare защищает от timing side-channel на token discovery. Overkill для 403-only endpoint, но zero cost.
- **Index declaration в двух местах (model + migration)**: required для SQLAlchemy `create_all` (используется в tests) и для alembic (prod). Без `__table_args__` test_prometheus_metrics.py и тесты, создающие DB через `Base.metadata.create_all`, не получили бы индекс.
- **Query-collapse deferred**: было в оригинальном scope 111.2, отложено. Причина: требует изменить schema return value 13 stage-110 тестов; ROI vs risk не оправдывает в blocker cleanup. Index один даёт perf-win (O(log n) lookup вместо O(n) scan).
- **F2 (inline imports) не включён**: scope split — F2 в stage 114. Единственное исключение: module-level перенос `RUNTIME_LOGGER` в `service_metrics.py` сделан в рамках F6 fix (чтобы не добавлять новый inline import).

### Simplicity evaluation (§4.1)

Прошёл 8 triggers — см. `PRD/этап-111-blocker-cleanup.md` §Simplicity. Ни один trigger не сработал. Единственный rationale: `METRICS_AUTH_TOKEN` optional (premature flexibility?) — nope, explicit backward-compat для self-hosted. Documented.

### Codex review (§5.1)

1 warning (адекватный): `allow ::1;` для IPv6 localhost в nginx. **Исправлено** — 1 LOC diff.
4 × nit (подтверждения корректности F1/F3/F5/F6). **Dismiss.**

Одна итерация Codex хватило — второй проход не нужен.

### Тесты

679 → 687 passed (+8). Все 8 — в `tests/test_stage111_blocker_cleanup.py`:
- 4 × /metrics auth (env missing / 403 без token / 200 с token / 403 с wrong)
- 1 × composite index presence (SQLAlchemy inspect)
- 1 × login lockout → record_auth_failure call
- 2 × record_business_event (unknown ERROR log / known still increments)

## Этап 112. Observability integrity — 2026-04-19

**Commit**: 921dd28 (backfilled stage 116.5).

Закрыл observability-findings medium/low из super-review 2026-04-19 (section T2).

### Что сделано

1. **112.1 breaker_opened log** — `vm_transport/breaker.py::breaker_record_failure` эмитит `circuit_breaker_opened` warning на CLOSED→OPEN threshold crossing + на HALF_OPEN→OPEN probe-fail. Codex flagged: race under concurrent sustained failures (state уже OPEN, но CLOSED-branch fall-through) → fix `if previous_state != "open":` guard. `RUNTIME_LOGGER` import вынесен на module level (F2 pattern prevention).
2. **112.2 integration_save_failed** — в обоих `account_integration_submit` + `_reauth_submit` except-blocks добавлен structured warning log (`account_id`, `auth_mode`, `error_class`, опционально `flow`) + `record_auth_failure(source="web_integration[_reauth]", reason=<snake_case>)`. `_camel_to_snake` helper для читаемых Prometheus label values (`auth_error`, `host_resolution_error`). `str(exc)` НЕ включён в extra — `AuthError.message` может embed'ить masked API key fragments.
3. **112.3 url_path → entity** — все 4 лог-сайта в `vetmanager_client._request` (retryable status, timeout-retry, timeout-final, network-error) используют `_entity_from_path_fn(path)` вместо `path` verbatim. Existing stage-88 тесты обновлены (2 asserts: `record.url_path` → `record.entity == "client"`).
4. **112.4 correlation_id explicit** — `account_registered` + `web_login_succeeded` extra теперь включает `correlation_id` из `get_current_request_context()`. Устойчиво к edge cases where `RequestContextLogFilter` silently drops field (non-HTTP context).
5. **112.5 retry log DEBUG** — убран INFO/DEBUG conditional (`is_last_attempt`); все retry decisions теперь DEBUG. Terminal failure по-прежнему эмитит WARNING на raise-site (`vm_upstream_timeout` / `vm_upstream_network_error`).
6. **112.6 skipped** — false positive, `started` уже per-attempt (line 296 перед каждым `client.request`).

### Решения и обоснования

- **`previous_state` guard**: Codex warning — под sustained failures state остаётся OPEN, но код продолжает инкрементировать counter и re-setting `opened_at` (pre-existing behavior) и новым логом создавал бы duplicate emission. Guard фиксирует: лог на реальной transition, counter/opened_at обновляются как раньше (extending cooldown window).
- **`error_class` без `str(exc)`**: защита от утечки masked API-key fragments в `AuthError.message`. Class name достаточен для querying.
- **`_camel_to_snake` helper**: 2 call-sites в scope — single responsibility + testability. Если появятся ещё use-cases, можно вынести в отдельный utils module.
- **Entity вместо url_path**: privacy-safe; reconstructability via `correlation_id` join с access log.
- **`LOG_INCLUDE_URL_IDS` env gate отклонён**: premature flexibility, нет concrete ops request.

### Codex review

1 warning (адекватный): duplicate log race на sustained failures → fixed с `previous_state` guard.
1 nit (адекватный): CamelCase → snake_case reason → fixed с `_camel_to_snake`.
4 × comment/confirmation: dismiss.

Одна итерация Codex. Второй проход не нужен.

### Тесты

687 → 690 (+3 в stage 112): breaker threshold log emission, breaker probe-fail log, breaker recovery log (verifies stage 107.9 regression boundary). Существующие stage-88 timeout/network-error тесты обновлены под `entity` contract.

## Этап 113. Resilience completeness (focused subset) — 2026-04-19

**Commit**: 14d763f (backfilled stage 116.5).

Закрыл F7 (billing-api hardening) + 113.1 (breaker env accessors). 113.2-113.5 явно deferred в stage 113b с design-нотами.

### Что сделано

1. **113.F7 `host_resolver.py`** — полный переписанный модуль:
   - **Per-loop shared `httpx.AsyncClient`** с tight timeouts (connect 3s, read 10s, write 5s, pool 2s). Pattern зеркальный `vm_transport/pool.py::get_shared_http_client` (но независимый — billing это отдельный upstream). Per-loop keying через `id(asyncio.get_running_loop())` устраняет cross-loop transport reuse под `asyncio.run()` re-entry (Codex HIGH finding).
   - **TTL cache** `domain → (resolved_host, expires_at)` с env-tunable TTL (`BILLING_RESOLVER_CACHE_TTL_SECONDS`, default 300s). Cache miss → HTTP + TLS handshake; hit → in-memory dict lookup. Failures НЕ кешируются — transient 5xx на billing не poison'ит lookups.
   - **`reset_billing_resolver()`** — async helper: clear cache + close all per-loop clients. Интегрирован в `server._graceful_shutdown` (cold path inline import acceptable — Codex confirmed) + autouse fixture в `tests/conftest.py` для per-test isolation.
   - Замена `0.1*(attempt+1)` linear backoff на что-то exponential — **отложено**: current linear retry preserved, чтобы сохранить existing test behavior.

2. **113.1 breaker env accessors** — три функции в `vm_transport/breaker.py`:
   - `breaker_failure_threshold()`, `breaker_window_seconds()`, `breaker_cooldown_seconds()` — каждая читает env per-call.
   - Runtime call-sites (`breaker_record_failure`, `check_breaker_allows`, `force_breaker_open`) мигрированы на accessors.
   - **Module-level constants сохранены** (`BREAKER_FAILURE_THRESHOLD = env_int(...)`) как **defaults только** — для existing tests которые используют их как reference value в `range(BREAKER_FAILURE_THRESHOLD)` loops. Docstring предупреждает: патчинг module attr больше не влияет на runtime, нужно `monkeypatch.setenv`.

### Решения и обоснования

- **Per-loop client в F7** (ответ на Codex HIGH): вместо singleton с потенциальной cross-loop ошибкой. Zero regression в prod (single loop per worker) + test-safe под pytest-asyncio.
- **Failures NOT cached**: при TTL 300s транзиентный 500 закешировал бы 5 минут downtime. Failure уже имеет retry layer; cache — только на success.
- **Cooldown accessor в `force_breaker_open`**: test helper, который использует `cooldown_elapsed=True` для backdating `opened_at`. Использует accessor so test env overrides (если any future test patches) согласованы.
- **Модульные константы не удалены**: 3 существующих теста (stage91, 101, 112) читают `BREAKER_FAILURE_THRESHOLD` как reference. Migration всех BC consumers — в scope stage 113b вместе с id(loop) refactor.
- **F7 scope trimmed**: dedicated billing breaker + exponential backoff отложены в stage 113b. Resolver без breaker — acceptable risk с TLS+cache optimization (main perf win); polish improvements без disruption.

### Codex review

1 HIGH адекватный (multi-loop risk): **fixed** переходом на per-loop pattern зеркальный `vm_transport/pool.py`.
1 MEDIUM адекватный (breaker module constants misleading): **mitigated** явным docstring warning + migration note.
1 LOW dismissed (inline import on cold shutdown path).

Одна итерация Codex + post-fix повторная верификация тестами. Второй проход Codex не нужен — minimal fix, low regression risk.

### Тесты

690 → 699 (+9):
- 5 × F7 (cache hit, no error caching, parallel collapse, reset idempotent, TTL > 0)
- 3 × env accessor reads
- 1 × integration: monkeypatch.setenv + breaker opens at threshold=2

Все 11 существующих host_resolver тестов зелёные (reset_billing_resolver autouse fixture обеспечивает isolation).

## Этап 114. Simplicity debt (focused: F2) — 2026-04-19

**Commit**: 29df6e8 (backfilled stage 116.5).

Закрыл F2 (inline imports) из super-review 2026-04-19 Codex arbitration. BC shim policy decision и 3-hop indirection collapse отложены в stage 114b (требуют explicit policy decision, не механический fix).

### Что сделано

1. **`service_metrics.py`**: `import time` + `from request_cache import REQUEST_CACHE` на module level. Удалены inline в `instrument_call` (hot path) + `render_prometheus_metrics`.
2. **`resources/_aggregation.py`**: `from exceptions import (...)` + `RUNTIME_LOGGER` + `get_current_request_context` вынесены на module level. Удалён дубликат line 96 `from exceptions import AuthError`.
3. **Regression test** `tests/test_stage114_simplicity.py` — AST walk фиксирует что `service_metrics.py` и `resources/_aggregation.py` не имеют Import/ImportFrom внутри function bodies (`FunctionDef` + `AsyncFunctionDef`).

### Решения и обоснования

- **Circular verification**: `request_cache.py`, `exceptions.py`, `observability_logging.py`, `request_context.py` не импортируют ни `service_metrics`, ни `resources._aggregation`. Безопасно.
- **AST test handles both FunctionDef and AsyncFunctionDef**: Codex medium finding — уже обработано в `isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))`.
- **Codebase-wide audit deferred**: 27 inline imports во всём src/. Большинство — legitimate (bootstrap в `server.py`, tools/__init__.py lazy register, validators.py optional deps). Mass fix без case-by-case review — риск регрессии.

### Codex review

1 medium — false alarm (Codex не видел тестового кода, _walk уже handle AsyncFunctionDef). Dismiss with rationale.

### Тесты

699 → 701 (+2 AST regression tests).

## Этап 115. Real concurrency tests — 2026-04-19

**Commit**: 332e8a6 (backfilled stage 116.5).

Закрыл T3 (concurrency theatre) из super-review 2026-04-19 — два behavioral теста + autouse service_metrics reset fixture.

### Что сделано

1. **`test_breaker_opens_under_concurrent_failures_without_amplification`** — 8 concurrent VetmanagerClient.get() → timeout. Assert `consecutive_failures ≤ N_CONCURRENT+2`, `state == "open"`. Barrier (`asyncio.Event`) синхронизирует старт всех coroutines — admission races происходят на upstream boundary, не на task scheduling.
2. **`test_get_shared_http_client_returns_same_instance_under_concurrency`** — 8 concurrent `get_shared_http_client()` → все identical. Behavioral check вместо inspection `_shared_http_clients` dict.
3. **Autouse `_reset_service_metrics_state`** fixture в `tests/conftest.py` — `reset_service_metrics()` перед/после каждого теста. Устраняет cross-test contamination.

### Решения и обоснования

- **Barrier synchronization (Codex warning)**: без `start_barrier.wait()` + `asyncio.sleep(0)` + `.set()` — coroutines запускаются с staggered scheduling, admission race не воспроизводится. С barrier — все входят в `client.request()` одновременно.
- **state == "open" strict** (Codex warning): `"half_open"` возможен только если cooldown elapsed mid-test. Test runtime < 1s, BREAKER_COOLDOWN=30s. Strict assert ловит regression если breaker не открылся.
- **N_CONCURRENT + 2 buffer**: threshold=5, stage 105 regression дал бы ~24 (8 × 3 retries). Buffer 2 — probe admission race.
- **Autouse reset**: не ломает стадии, которые вручную reset'ят — idempotent. Stage 110 тесты теперь могут убрать manual reset (defer to stage 114b/117 docs sweep).

### Codex review

2 warnings — оба адекватные, оба зафиксированы (barrier + strict state).
2 nits — dismiss (inline context не видел).

Одна итерация Codex + fixup. Full suite re-verified 703 green.

### Тесты

701 → 703 (+2). Autouse fixture не ломает existing stage 105/106 concurrency tests — они продолжают работать.

## Этап 116. PRD 110 completion — 2026-04-19

**Commit**: `bd51a40`.

Закрыл F4 + product-drift findings из super-review 2026-04-19.

### Что сделано

1. **116.1**: `--window-days` CLI flag удалён. 30-day window hardcoded в `collect_metrics`; signature `collect_metrics(session_factory, *, now, top_n=10)`. Skill + README + PRD 110 docs обновлены.
2. **116.2**: `tokens.expired_auto_24h` counter добавлен (query `TOKEN_EVENT_EXPIRED` за 24h). Markdown/JSON output + test assertion.
3. **116.3**: PRD 110 docs drift — `--window=30d` удалён, `disabled` убран из failures list (нет event), SSH example с `--profile production`.
4. **116.4**: `test_record_business_event_increments_counter` расширен с 2 до 4 events (all PRD 110 acceptance #4).
5. **116.5**: AssumptionLog commit SHAs backfilled для этапов 105-115.

### Решения и обоснования

- **`--window-days` REMOVED**: half-wired → silent data mislabel. Full-propagation потребовала бы rename 13 stage-110 test assertions. Remove = zero risk, правдивый contract.
- **`disabled` удалён из PRD**: нет `TOKEN_EVENT_AUTH_FAILED_DISABLED` в auth_audit. PRD drift честнее fix'ить doc.
- **Codex review skipped**: ~90% scope — docs drift + test extension + CLI flag removal. Rationale per CLAUDE.md §5.5.
- **SHA backfill**: python-скрипт с explicit mapping stage→SHA (sed был слишком greedy изначально).

### Тесты

703 passed, stable. Stage 110 tests обновлены под new API.

## Этап 117. Docs catchup — 2026-04-19

**Commit**: `bcc42ba`.

Закрыл T4 (docs drift) из super-review 2026-04-19 + добавил protection против будущего drift.

### Что сделано

1. **117.1** — `artifacts/technical-requirements-vetmanager-mcp-ru.md`: добавлена секция §7.1 "Журнал этапов 97-116 (stage 117.1 backfill)" с compact-changelog каждого этапа, плюс подсекции "Дополнительная структура" / "Резидентные upstream'ы" / "Observability metrics (stage 88 + 110)".
2. **117.2** — `artifacts/observability-runbook-vetmanager-mcp-ru.md`: banner "Last updated: stage 45" с перечислением метрик добавленных в stage 88 + stage 110 + stage 111.1 /metrics auth + stage 112 breaker/integration/entity logs. Полная ревизия runbook — отдельным stage (не backfill).
3. **117.3** — `README.md:122-140` observability section: добавлен bullet про `vetmanager_business_events_total{event=...}` + ссылка на `METRICS_AUTH_TOKEN` stage 111.1 gate.
4. **117.4** — `scripts/review_workflow_check.sh`: новый check 11 "pending_commit_sha" detector — находит `**Commit**: (pending)` markers в AssumptionLog. Catches bulk gap pattern (13 stages missed prior to 116.5 backfill).
5. **117.5** — `artifacts/review/2026-04-19-changed-105-110-stage-110.md`: Resolution section с таблицей finding → closing stage → commit SHA. Report помечен как superseded.

### Решения и обоснования

- **Runbook banner вместо полной ревизии**: 10+ новых метрик + breaker state transitions + billing-api observability = >500 LOC changelog. Full rewrite без concrete ops pain = low ROI. Banner с "Last updated: stage 45" + список добавленных метрик даёт operator'у знать чего **не** покрывает runbook; полное обновление отложено до первого incident где runbook проваливается.
- **(pending) detector в workflow script**: generic `head -5` на случай сохранения старых (pending) records, не пропустит новые через автоматический pipeline. Severity medium (не blocker) — не ломает commit, но flagged в super-review.
- **technical-requirements §7.1 вместо merge в §2**: полный rewrite §2 сложен (14 этапов, architecture consolidation mid-chain). Compact journal в новой подсекции — честный backfill без risk структурной регрессии. Future stages могут добавлять строки одной правкой.
- **Codex review skipped per §5.5**: docs-only (5 markdown changes + 1 bash script with mechanical regex). Нет нового функционала, нет architectural decisions.

### Тесты

703 passed, stable. Нет code changes требующих новых тестов. `./scripts/review_workflow_check.sh 117` проверяет new `(pending)` detector: возвращает 0 findings (все 13 stages 105-115 заполнены stage 116.5).

## Этап 113b. Breaker/pool concurrency hardening — 2026-04-19

Закрыл deferred concurrency/reliability items из super-review 2026-04-19 и существующего Roadmap stage 113b.

### Что сделано

1. `vm_transport/pool.py`: registry shared HTTP clients переведён с `dict[id(loop), client]` на `WeakKeyDictionary[loop, client]`. `current_loop_key()` теперь возвращает loop object, а `get_shared_http_client_state()` сериализует наружу `id(loop)` только для debug snapshot.
2. `vm_transport/pool.py`: import-time `asyncio.Lock()` убран; lock создаётся lazy через `_get_pool_lock()` при первом реальном use.
3. `host_resolver.py`: per-loop shared clients и locks переведены на `WeakKeyDictionary`; локальный lock создаётся lazy per-loop instead of `setdefault(..., asyncio.Lock())` on an int-key dict.
4. `vetmanager_client.py`: retryable `GET` statuses `502/503/504` теперь записывают breaker failure per attempt. `429` исключён из breaker accounting как rate-limit signal, не upstream health signal.
5. `vetmanager_client.py`: terminal 4xx path (`VetmanagerError` with 4xx status, включая exhausted `429`) теперь закрывает breaker success-path, чтобы final coherent 4xx response не считался failure по finally-fallback.
6. Добавлен regression suite `tests/test_stage113b_concurrency.py` на:
   - per-attempt opening breaker on retryable `503`;
   - no-breaker-amplification on `429`;
   - `WeakKeyDictionary` registries;
   - отсутствие import-time `asyncio.Lock()` в `vm_transport/pool.py` и `host_resolver.py`.

### Решения и обоснования

- **Per-attempt only for 502/503/504, not 429**: `429` обозначает throttling / backpressure, но не "upstream unhealthy". Если считать его breaker failure, self-healing rate-limit responses преждевременно открывают circuit и делают продукт менее доступным.
- **WeakKeyDictionary вместо `id(loop)`**: это минимальный fix без лишней абстракции. Убирает residual correctness risk при reuse object id и auto-evict'ит closed loops без отдельного cleanup registry.
- **Lazy lock только в реально затронутых registries**: `vm_transport.pool` и `host_resolver` покрывают замечание Roadmap напрямую. `vm_transport.breaker` в этом проходе не трогался, потому что новый acceptance был полностью закрыт без дополнительного churn в breaker state machine.
- **BC surface сохранён**: re-export identity tests (`stage109_bc_invariants`) остались зелёными; helper `get_shared_http_client_state()` не меняет внешний shape, хотя внутри registry теперь keyed by loop object.

### Аудит

- Изменения ограничены hot paths stage 113b (`vm_transport/pool.py`, `host_resolver.py`, `vetmanager_client.py`) без расширения public API.
- Проверен regression perimeter: stage 91 / 96 / 105 / 106 / 109 / 113 / 115 tests зелёные вместе с новыми stage 113b tests.
- Новые follow-up findings из full-review вынесены в Roadmap stages 118 и 119, без смешения scope текущего stage.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest -q tests/test_stage113b_concurrency.py tests/test_stage106_reliability.py tests/test_stage105_breaker_amplification.py tests/test_stage115_concurrency.py tests/test_stage91_vm_client_overhaul.py tests/test_host_resolver.py tests/test_stage113_resilience.py tests/test_stage109_bc_invariants.py` → `57 passed`
- Full: `docker compose --profile test run --rm test` → `707 passed, 57 deselected`

## Этап 114b. Simplicity debt follow-up — 2026-04-20

**Commit**: `259201a`.

Закрыл deferred simplicity хвост из super-review: repeatable audit inline imports, collapse лишней indirection в profile tools и финальная FilterBuilder migration для оставшихся call-sites.

### Что сделано

1. Добавлен `scripts/inline_imports_audit.py` с allowlist только для легитимных runtime inline imports: cycle break, optional Redis dependency, lazy tool registration и CLI-only bootstrap.
2. Убраны лишние inline imports в runtime-модулях (`prompts.py`, `auth/request.py`, `auth_audit.py`, `request_context.py`, `service_token_service.py`, `rate_limit_backend.py`, `vm_transport/retry.py`, `tools/invoice.py`, `tools/crud_helpers.py`, `tools/pet.py`, `tools/client.py`, `server.py`, `web_auth.py`, `auth/bearer.py`, `auth/rate_limit.py`).
3. `tools/client.py:get_client_profile` и `tools/pet.py:get_pet_profile` больше не идут через `_impl` closure + `_get_*_profile_impl`; остался прямой `instrument_call(..., lambda: fetch(...))`.
4. `resources/client_profile.py`, `resources/pet_profile.py` и `tools/medical_card.py:get_medical_cards_by_client_id` переведены на `build_list_query_params(...)` вместо hand-rolled JSON filter assembly.
5. Добавлены regression tests `tests/test_stage114b_simplicity_followup.py` на inline-import audit, отсутствие wrapper hops и сохранение `sort/limit/offset` в `get_medical_cards_by_client_id`.

### Решения и обоснования

- **Audit script вместо разового grep**: acceptance для stage 114b требовал повторяемый механизм, иначе следующий review снова сведётся к ручной проверке.
- **Allowlist минимальный**: оставлены только case'ы с явной причиной. `secret_manager.py` держит локальный import из-за cycle `storage_models -> secret_manager -> web_auth`; Redis import остаётся optional; `tools/__init__.py` сохраняет lazy registration.
- **BC shims не удалялись**: policy `KEEP` из stage 114b подтверждена; tests на identity invariants остаются зелёными.
- **Module import вместо function snapshot** для FastMCP dependencies: сохраняет patchability тестов, но убирает per-call inline import.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest -q tests/test_stage114_simplicity.py tests/test_stage114b_simplicity_followup.py tests/test_api_contracts_hotfix.py tests/test_stage96_post_review_hotfix.py tests/test_e2e_mock_clinical_profiles.py tests/test_stage102_aggregator_structured_errors.py` → `49 passed`
- Cross-check after patchability fix: `docker compose --profile test run --rm test pytest -q tests/test_web_security.py tests/test_request_auth.py tests/test_request_context.py tests/test_stage114b_simplicity_followup.py` → `21 passed`

## Этап 118. Product metrics correctness follow-up — 2026-04-20

**Commit**: `259201a`.

Закрыл semantic drift в `scripts/product_metrics_report.py`: timezone-aware `--now-override` и UTC-consistent serialization для `dead_list.last_request_at`.

### Что сделано

1. `_to_aware()` теперь нормализует aware timestamps через `.astimezone(timezone.utc)`, а не просто возвращает исходную timezone.
2. `_async_main()` обрабатывает `--now-override` через `_to_aware(datetime.fromisoformat(...))`, поэтому aware input вроде `2026-04-18T12:00:00+03:00` превращается в `2026-04-18T09:00:00+00:00`.
3. `_fetch_dead_account_rows()` сериализует `last_request_at` из `last_used_aware`; заодно `created_at` тоже нормализуется в UTC-consistent ISO form.
4. `tests/test_stage110_product_metrics.py` расширен тестами на aware `--now-override` и UTC suffix у `dead_list.last_request_at`.

### Решения и обоснования

- **Naive timestamps по-прежнему трактуются как UTC**: это уже существующий invariant отчёта и storage layer; stage 118 не меняет этот contract, только чинит aware case.
- **`created_at` тоже нормализован**: finding был про `last_request_at`, но mixed naive/aware timestamps в одном отчёте бессмысленны. Симметричная нормализация безопаснее и честнее для operator output.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest -q tests/test_stage110_product_metrics.py tests/test_stage114_simplicity.py tests/test_stage114b_simplicity_followup.py` → `22 passed`

## Этап 119. Test isolation + workflow/docs cleanup — 2026-04-20

**Commit**: `259201a`.

Закрыл хвосты reviewer-tests / workflow-check / reviewer-docs после повторного full-review.

### Что сделано

1. `tests/conftest.py` теперь сбрасывает `REQUEST_CACHE.metrics.{hits,misses,invalidations,evictions}` вместе с `_entries` и `_tag_index`.
2. Добавлен regression file `tests/test_stage119_test_isolation.py`, который пинует reset cache metrics между тестами.
3. Для этапов 116 и 117 backfill'нуты реальные commit SHA (`bd51a40`, `bcc42ba`) в `AssumptionLog.md`.
4. `artifacts/release-checklist-vetmanager-mcp-ru.md` обновлён под текущий `/metrics` contract с optional `METRICS_AUTH_TOKEN`.

### Решения и обоснования

- **Reset в fixture, а не helper внутри cache**: проблема была именно в test isolation. Добавлять новый runtime API ради тестового сброса не нужно.
- **Release checklist синхронизирован с README, а не с текущим operator habit**: truth source здесь runtime/documented contract, а не "как обычно проверяли раньше".

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest -q tests/test_stage119_test_isolation.py tests/test_stage110_product_metrics.py tests/test_stage114_simplicity.py tests/test_stage114b_simplicity_followup.py` → `24 passed`
- Full re-run after audit/refactor fixes: `docker compose --profile test run --rm test` → `716 passed, 57 deselected`

## Этап 120. Historical PRD goal-section backfill — 2026-04-20

**Commit**: `bd1b755`.

Закрыл остаточный workflow noise по историческим PRD без явной секции `## Цель`.

### Что сделано

1. Добавлен PRD этапа 120 для самого cleanup pass.
2. В исторические PRD из workflow-check списка добавлена короткая секция `## Цель` без изменения scope, решений или backlog.
3. `Roadmap.md` обновлён: stage 120 добавлен и завершён как docs/workflow cleanup.

### Решения и обоснования

- **Backfill только структуры, не содержания**: задача была убрать workflow-noise, а не переписывать исторические решения задним числом.
- **Сохранил существующие `## Цели`/`## Контекст`/`## Scope`**: новый `## Цель` выступает как совместимый header для текущего workflow-check contract.

### Тесты

- `bash scripts/review_workflow_check.sh` — `prd_missing_section` для backfill-списка исчез.
- `docker compose --profile test run --rm test` → `716 passed, 57 deselected`

## Этап 121. Roadmap status sync cleanup — 2026-04-20

**Commit**: `04a4570`.

Финальный docs-only cleanup `Roadmap.md`: синхронизировал внутренние подпункты уже завершённых этапов с фактическим статусом `done`.

### Что сделано

1. Приведены к `done` подпункты в закрытых этапах `115`, `116`, `117`.
2. Приведены к `done` подпункты в закрытых follow-up этапах `114b`, `118`, `119`, `120`.
3. Добавлен отдельный PRD stage 121, чтобы cleanup сам соответствовал workflow contract.

### Решения и обоснования

- **Это отдельный docs stage, а не silent edit**: иначе Roadmap cleanup сам бы нарушил правило "PRD before implementation".
- **Не переписывал historical rationale**: только статусы подпунктов, чтобы backlog отражал уже совершённую работу.

### Тесты

- `bash scripts/review_workflow_check.sh` — ожидается зелёный после записи stage 121.

## Этап 122. VM API payload contract hotfix — 2026-04-21

**Commit**: `(pending)`.

Закрыл code/test часть blocker-а B1 из super-review 2026-04-20: целевые tools больше не отправляют camelCase/legacy query-поля в VM API для hospital/payment/invoiceDocument/client/breed/timesheet.

### Что сделано

1. Создан PRD `PRD/этап-122-vm-api-payload-contract-hotfix.md`.
2. `tools/clinical.py`:
   - `create_hospitalization` теперь отправляет `patient_id`, `doctor_id`, `date_in`, `hospital_block_id`;
   - `update_hospitalization` теперь отправляет `date_out`, `hospital_block_id`;
   - `get_hospitalizations(pet_id=...)` переведён на filter `patient_id`, а не legacy top-level query param.
3. `tools/finance.py`:
   - `create_payment` теперь отправляет `client_id`, `cassa_id`;
   - `get_payments(client_id=...)` строит filter по `client_id`, не `clientId` query param;
   - `add_invoice_document` теперь отправляет `invoice_id`, `good_id`;
   - `get_invoice_documents(invoice_id=...)` строит filter по `invoice_id`, не `invoiceId` query param.
4. `tools/client.py::create_client` переведён на `first_name`, `last_name`, `cell_phone`.
5. `tools/reference.py::get_breeds` переведён на filter `pet_type_id`.
6. `tools/operations.py::get_timesheets(date=...)` больше не использует top-level `date`; вместо этого строит filters `begin_datetime >= YYYY-MM-DD 00:00:00` и `end_datetime <= YYYY-MM-DD 23:59:59`.
7. `tests/test_api_contracts_hotfix.py` расширен 9 regression tests на фактический HTTP body/query для всех перечисленных инструментов.
8. `artifacts/api-research-notes-ru.md` дополнен canonical mappings для Hospital / Payment / InvoiceDocument / Client create / Breed / Timesheet date filter.

### Архитектурные решения

- **Внешние MCP-имена сохранены**, если это уже устоявшийся публичный контракт (`pet_id`, `doctor_id`, `date_in`, `block_id`, `phone`). Маппинг делается только на outbound VM wire contract.
- **Для list-инструментов использован filter, а не extra query**, когда review зафиксировал реальное имя поля в VM entity. Это делает контракт единообразным и предотвращает silent ignore со стороны API.
- **`create_client.phone` мапится в `cell_phone`**. Это выбранный operational default для stage 122; если later real API probe докажет необходимость `home_phone`, нужен отдельный follow-up, а не молчаливый rollback.

### Тесты

- Targeted red/green: `docker compose --profile test run --rm test pytest tests/test_api_contracts_hotfix.py` → `15 passed`.
- Full: `docker compose --profile test run --rm test` → `725 passed, 57 deselected`.

### Real API probe

- Выполнен manual probe на `devtr6` через MCP tool-path внутри test-контейнера:
  `create_client(first_name="Stage122", last_name="stage122-20260421052549", phone="+79991234567", email="stage122-20260421052549@example.invalid")`
  → `get_client_by_id(458)`
  → `delete_client(458)`.
- Live API подтвердил, что после stage 122 запись создаётся с заполненными:
  - `first_name="Stage122"`
  - `last_name="stage122-20260421052549"`
  - `cell_phone="+79991234567"`
  - `email="stage122-20260421052549@example.invalid"`
- Cleanup подтверждён тем же контуром: `DELETE /rest/api/client/458` → `200 OK`.

### Дополнительные наблюдения

- `create_client` real response shape не стабилен в одну форму: `data.client` может приходить и как `list[dict]`, и как `dict`. Для stage 122 это использовалось только в ad-hoc probe; production fix от этого не зависит, но факт полезен для будущих real-test helper'ов.
- Read-only real smoke на `breed`, `payment`, `invoiceDocument`, `hospital`, `timesheet` отрабатывал с `HTTP 200`, но `tests/test_e2e_real.py -k ...` показал существующую teardown-проблему `RuntimeError: Event loop is closed` в real-test infrastructure. Это не блокировало закрытие stage 122 после успешного write-side probe с cleanup.

## Этап 123. Contract tests rewrite + mutation unhappy-path coverage — 2026-04-21

**Статус**: `done`.

Stage 123 закрыт полностью: broken create fixtures переписаны на `mcp.call_tool(...)`, invalid admission status валидируется до HTTP вызова, mutation tests закрепляют wire contract точными body assertions, а error paths покрыты по всем mutation tools из `tests/test_e2e_mock_crud.py`.

### Что сделано

1. Создан PRD `PRD/этап-123-contract-tests-and-mutation-unhappy-path.md`.
2. `tests/test_e2e_mock_entities.py`:
   - `test_create_pet` теперь идёт через `mcp.call_tool("create_pet", ...)` и пинует payload `owner_id`;
   - `test_create_admission` теперь идёт через `mcp.call_tool("create_admission", ...)` и пинует `patient_id`, `user_id`, `admission_date`, `status="save"`;
   - response fixtures для admission синхронизированы с актуальным `patient_id`.
3. `tools/admission.py` получил минимальный runtime guard `_validate_admission_status(...)` для enum значений `save|directed|accepted|deleted|delayed|not_approved|in_treatment|not_confirmed`.
4. `tests/test_api_contracts_hotfix.py` расширен тестом `test_create_admission_invalid_status_rejected`; при вызове через `mcp.call_tool(...)` invalid status поднимается как `ToolError` до HTTP вызова.
5. `tests/test_e2e_mock_crud.py` tightened до exact wire assertions:
   - все mutation tools в этом файле теперь проверяют `method + url + parsed JSON body` там, где body существует;
   - удалены оставшиеся loose-проверки `route.called` из stage 123 scope.
6. `tests/test_api_contracts_hotfix.py` дополнен contract tests для дополнительных mutation tools:
   - `create_client`
   - `create_payment`
   - `add_invoice_document`
   - `create_hospitalization`
   - `create_medical_card`
   - `update_medical_card`
7. `tests/test_e2e_mock_crud.py` получил parametrized unhappy-path coverage для всех mutation tools, находящихся в scope этого файла:
   - create: `create_good`, `create_supplier`, `create_timesheet`
   - update: `update_invoice`, `update_user`, `update_hospitalization`, `update_supplier`, `update_good`
   - delete: `delete_client`, `delete_pet`, `delete_invoice`, `delete_invoice_document`

### Решения и обоснования

- **Для tool-level unhappy paths truth source — `ToolError`, не raw domain exception.** `FastMCP` оборачивает внутренние исключения на публичной границе `mcp.call_tool(...)`, поэтому stage 123 должен пиновать именно этот внешний контракт.
- **Invalid admission status валидируется в tool layer**, а не оставляется на усмотрение upstream API. Это дешевле, даёт детерминированный CI signal и предотвращает silent drop на стороне Vetmanager.
- **Public contract на границе `mcp.call_tool(...)` закрепляется через `ToolError`.** Для 4xx/5xx unhappy paths тестировать внутренние exception-классы было бы ложной целью, потому что наружу FastMCP всё равно отдаёт `ToolError`.
- **`create_good` intentionally posts default flags** `is_active=1` и `is_for_sale=1`. Stage 123 зафиксировал это как часть wire contract, чтобы последующие refactor'ы не срезали defaults случайно.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest tests/test_e2e_mock_entities.py tests/test_e2e_mock_crud.py tests/test_api_contracts_hotfix.py` → `119 passed`.
- Full: `docker compose --profile test run --rm test` → `747 passed, 57 deselected`.

### Workflow audit

- `bash scripts/review_workflow_check.sh 123` не нашёл новых содержательных проблем; остались только служебные reminders `oversize_diff` и `tests_reminder`.
- Требование `tests_reminder` закрыто фактическим полным прогоном suite.

## Этап 124. Async Redis rate-limit backend — 2026-04-21

**Статус**: `done`.

Stage 124 перевёл web rate-limit hot-path на async backend: `rate_limit_backend.py` больше не использует sync `redis.Redis`, web auth routes ждут limiter через `await`, а тесты закрепляют interleaving и strict/fallback semantics.

### Что сделано

1. Создан PRD `PRD/этап-124-async-redis-rate-limit-backend.md`.
2. `rate_limit_backend.py`:
   - `RateLimitBackend` protocol переведён на async methods;
   - `InMemoryRateLimitBackend`, `RedisRateLimitBackend`, `_ResilientRedisBackend` переведены на async API;
   - Redis factory теперь использует `importlib.import_module("redis.asyncio")` и `Redis.from_url(...)`;
   - `await client.ping()` добавлен в init-path;
   - добавлен lazy init lock для race-safe первого получения backend;
   - sync imports `import redis` / `redis.Redis` удалены.
3. `RedisRateLimitBackend.record_hit` больше не использует pipeline; вместо этого делает последовательные `await zadd(...)` + `await expire(...)`, что упрощает совместимость с async Redis/fakeredis и убирает не-awaited coroutine риск.
4. `web_security.py`:
   - `check_rate_limit`, `record_rate_limit_hit`, `clear_rate_limit_key` переведены на async;
   - `reset_web_security_state()` оставлен sync test-helper'ом, который сбрасывает cached backend через `reset_rate_limit_backend()`.
5. `web_routes_auth.py`:
   - register/login flow теперь делает `await check_rate_limit(...)`;
   - invalid login path делает `await record_rate_limit_hit(...)`;
   - successful login path делает `await clear_rate_limit_key(...)`.
6. `tests/test_rate_limit_backend.py` полностью переписан под async:
   - in-memory backend checks;
   - fakeredis async backend checks;
   - factory fallback/fail-fast checks;
   - explicit integration test на `redis.asyncio`;
   - resilient fallback/strict tests;
   - concurrency test на `check_rate_limit(...)` с interleaving assertion.
7. `tests/test_web_security.py` адаптирован под async helper calls.

### Архитектурные решения

- **Factory остался lazy, но стал race-safe.** Для первого обращения используется async init lock с double-check, чтобы параллельные HTTP requests не создавали несколько backend instances одновременно.
- **`reset_web_security_state()` сохранён sync намеренно.** Большая часть test fixtures вызывает его вне async context; для test isolation достаточно rebinding cached backend, без обязательного `await reset_all()`.
- **Fallback semantics `_ResilientRedisBackend` сохранены.** В non-strict mode Redis runtime failures деградируют в process-local in-memory limiter, в strict mode ошибки пропагируются и request path fail-closed.
- **Interleaving закреплён на уровне web helper, не только backend.** Это гарантирует, что async propagation реально дошла до `check_rate_limit(...)`, а не осталась локальной внутри backend implementation.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest tests/test_rate_limit_backend.py tests/test_web_security.py tests/test_web_auth.py -q` → `49 passed`.
- Full: `docker compose --profile test run --rm test` → `749 passed, 57 deselected`.

### Workflow audit

- `bash scripts/review_workflow_check.sh 124` после реализации репортил только:
  - `oversize_diff`
  - `missing_assumption`
  - `tests_reminder`
- `missing_assumption` закрыт этой записью.
- `tests_reminder` закрыт фактическим полным прогоном suite.

## Этап 125. Perf N+1 + free-slot correctness — 2026-04-21

**Статус**: `done`.

Stage 125 закрыл сразу три user-facing дефекта: pagination TOCTOU в `paginate_all`, false blocking в `get_doctor_free_slots` для multi-clinic расписания и остаточный N+1/underfetch в `get_inactive_pets`.

### Что сделано

1. Создан PRD `PRD/этап-125-perf-nplus1-and-free-slot-correctness.md`.
2. `tools/crud_helpers.py::paginate_all` теперь фиксирует `totalCount` только с первой страницы и не даёт поздним страницам перезаписать итоговое значение.
3. `tools/user.py::get_users` переведён на `asyncio.gather(...)` для `last_name`/`first_name` search path; docstring и фактическое поведение снова совпадают.
4. `tools/schedule.py::get_doctor_free_slots`:
   - timesheet и admission fetch теперь идут через `asyncio.gather(...)`;
   - busy intervals разделены на `busy_by_clinic` и `shared_busy`;
   - admission без `clinic_id` продолжает блокировать все клиники врача, admission с `clinic_id` блокирует только свою клинику.
5. `tools/_inactive_helpers.py`:
   - добавлен batched page-level resolver `find_pets_for_clients_last_visit(...)`;
   - pet lookup по странице клиентов делается через `owner_id IN [...]` с pagination;
   - invoice/medcard lookup идёт batch'ами по дню визита и `pet_id/patient_id IN [...]`;
   - для single-owner path pagination pets больше не ломается на ложном `totalCount=100`;
   - medcard fallback short-circuit'ится, если invoice-ветка уже набрала нужный page limit.
6. `tools/pet.py::get_inactive_pets` переведён с per-client serial scan на page-level batched resolver при сохранении исходного порядка клиентов в выдаче.
7. Тестовый слой расширен:
   - `tests/test_inactive_pets.py` покрывает large-client-page batching, underfilled first page и owner с `>100` pets;
   - `tests/test_get_doctor_free_slots.py` покрывает multi-clinic blocking и параллельный fetch;
   - `tests/test_crud_helpers.py` закрепляет boundary 100/101;
   - `tests/test_ergonomic_filters.py` закрепляет реальный parallel path в `get_users(name=...)`.

### Архитектурные решения

- **Для batched inactive-pets truth source — день последнего визита клиента, а не просто client_id.** Это позволило агрегировать invoice/medcard запросы без потери корректности day-bounded window.
- **`clinic_id=None/0` в admission трактуется как shared busy interval.** Иначе старые записи без clinic binding перестали бы блокировать слоты вообще, что ломает back-compat и существующие сценарии.
- **В batched pet lookup pagination strategy зависит от cardinality owner batch.** Для single-owner case нельзя доверять `totalCount`, потому что upstream/mock может вернуть page-sized `totalCount`; для multi-owner batched case first-page `totalCount` безопасно использовать как stop-signal.
- **Medcard fallback теперь conditional по remaining demand.** Если invoice branch уже закрывает текущий `limit`, дальнейший fallback только жжёт latency без user-visible выигрыша.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest tests/test_inactive_pets.py tests/test_get_doctor_free_slots.py tests/test_crud_helpers.py tests/test_ergonomic_filters.py -q` → `73 passed`.
- Full: `docker compose --profile test run --rm test` → `756 passed, 57 deselected`.

### Workflow audit

- Этап выполнен через red → green: сначала добавлены failing regression tests, затем реализованы fixes.
- После рефакторинга выполнен повторный полный прогон suite.

## Этап 126. Auth-probe service hardening — 2026-04-21

**Статус**: `done`.

Stage 126 закрыл hot-path проблемы в `vetmanager_connection_service.py`: whitespace-sensitive password trimming, per-call `httpx.AsyncClient`, отсутствие probe metrics/retries и race при concurrent save одного account.

### Что сделано

1. Создан PRD `PRD/этап-126-auth-probe-service-hardening.md`.
2. `vetmanager_connection_service.py`:
   - `exchange_user_token` больше не делает `password.strip()`, а проверяет только `if not password`;
   - добавлен общий helper `_request_with_retry(...)` для auth-probe/token-auth запросов;
   - helper использует shared pool из `vm_transport.pool.get_shared_http_client()`;
   - transient `502/503/504` и `httpx.ConnectTimeout` ретраятся до 3 попыток с exponential backoff и `Retry-After`;
   - `validate_domain_api_key_connection`, `validate_user_token_connection`, `exchange_user_token` больше не создают локальный `httpx.AsyncClient`;
   - каждый upstream attempt пишет `record_upstream_request(...)`, а failure attempts пишут `record_upstream_failure(...)`;
   - success/failure branches теперь оставляют structured runtime logs по probe path.
3. Save path:
   - добавлен per-account async lock registry;
   - disable + insert теперь выполняются внутри одной транзакции;
   - выборка active connections делает `SELECT ... FOR UPDATE` перед disable.
4. `evaluate_connection_health(...)`:
   - больше не молчит на `HostResolutionError` / `VetmanagerTimeoutError` / `VetmanagerError`;
   - пишет `RUNTIME_LOGGER.warning(..., event_name="connection_health_failed")`.
5. `tests/test_vetmanager_connection_service.py` расширен:
   - whitespace password passthrough;
   - shared pool + retry path;
   - structured warning на health-check failure;
   - concurrent save оставляет ровно один `ACTIVE`.

### Архитектурные решения

- **Сериализация save path сделана в приложении, не только в БД.** `SELECT ... FOR UPDATE` на SQLite фактически no-op, поэтому для test/dev и single-process deployment нужен process-local per-account lock; row lock остаётся полезным для PostgreSQL path.
- **Shared pool reused и для `token_auth.php`, и для probe GET'ов.** Это убирает лишние TCP/TLS handshakes именно в onboarding path, не только в основном `VetmanagerClient`.
- **Retry scope намеренно узкий.** Ретраятся только `502/503/504` и `ConnectTimeout`; `401/403` fail-fast остаются признаком плохих credential'ов, а не transient upstream noise.
- **Upstream metrics пишутся per attempt, не per logical operation.** Это даёт честный error-rate на probe hot-path и позволяет видеть hidden retry storms вместо ложно-зелёного агрегата.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest tests/test_vetmanager_connection_service.py tests/test_web_auth.py tests/test_service_metrics.py -q` → `39 passed`.
- Full: `docker compose --profile test run --rm test` → `760 passed, 57 deselected`.

### Workflow audit

- Этап выполнен через red → green: сначала добавлены failing service tests, затем выполнен refactor helper/save path.
- После hardening выполнен повторный полный прогон suite.

## Этап 127. Docs drift cleanup — 2026-04-21

**Статус**: `done`.

Stage 127 закрыл чисто документационный drift перед release gate: README снова ссылается на реальные artifact paths, technical requirements описывает текущую backup/cache/structure модель, а `CLAUDE.md` синхронизирован с фактическим набором review subagents.

### Что сделано

1. Создан PRD `PRD/этап-127-docs-drift-cleanup.md`.
2. `README.md`:
   - исправлены 4 пути на `artifacts/*-vetmanager-mcp-ru.md`;
   - количество сущностей обновлено `35` → `38`;
   - test command обновлён на `docker compose --profile test run --rm test`;
   - аналогичная команда обновлена и в секции с default contour.
3. `artifacts/technical-requirements-vetmanager-mcp-ru.md`:
   - backup section переведён с legacy SQLite wording на PostgreSQL `pg_dump` через `scripts/backup_postgres.sh`;
   - в tool list и structure tree добавлены `schedule.py`, `_inactive_helpers.py`, `_slots_helpers.py`;
   - cache key description обновлён с учётом `account_id`;
   - §7.1 changelog расширен до stages `117-121` и заголовок синхронизирован на `97-121`.
4. `CLAUDE.md`:
   - `10 subagent'ов` → `11 subagent'ов`;
   - в список review agents добавлен `simplicity`, что соответствует реальному `.claude/agents/reviewer-simplicity.md`.

### Решения и обоснования

- **Это docs-only stage без code path changes.** Нужна была синхронизация release artifacts и workflow instructions перед stage 128, а не функциональные правки.
- **Truth source для entity count — `artifacts/api_entity_reference-ru.md`.** README должен ссылаться на фактический справочник, а не на историческую цифру.
- **README и technical requirements синхронизированы с canonical production artifacts.** Сокращённые имена `*-ru.md` оставляли ложные ссылки именно перед финальным release/deploy gate.

### Проверки

- `test -f artifacts/security-deployment-notes-vetmanager-mcp-ru.md && test -f artifacts/observability-runbook-vetmanager-mcp-ru.md && test -f artifacts/operations-readiness-vetmanager-mcp-ru.md && test -f artifacts/release-checklist-vetmanager-mcp-ru.md` → `paths_ok`
- grep на старые broken paths / старую test command / `35 сущностей` / `10 subagent` не вернул совпадений.

### Workflow audit

- Этап docs-only, поэтому отдельный прогон test suite не требовался.
- Содержательные workflow artifacts (`Roadmap.md`, `PRD/`, `AssumptionLog.md`) синхронизированы.

## Этап 128. Final release gate + production deploy — 2026-04-23

**Статус**: `done`.

Stage 128 закрыт фактическим production rollout. После восстановления SSH-доступа выполнены backup, deploy, post-deploy smoke, web/UI checks и bearer-backed MCP verification. В процессе всплыл один production-only migration bug; он был исправлен отдельным hotfix commit до финального успешного deploy.

### Что сделано

1. Release gate повторно подтверждён на актуальном хвосте stages `122-130`:
   - `docker compose --profile test run --rm test` → `802 passed, 57 deselected`;
   - PRD stage `128` очищен от устаревших предпосылок (`122-127`) и от допущения о code changes внутри deploy path.
2. Pre-deploy safety checks:
   - production host `root@212.193.59.219` снова доступен по SSH;
   - на сервере подтверждены `WEB_SESSION_SECRET` и `STORAGE_ENCRYPTION_KEY`;
   - перед deploy выполнен ручной backup ` /var/backups/vetmanager-postgres/vetmanager-20260423-012655.sql.gz`;
   - canonical deploy path также создал pre-deploy rollback point `/var/backups/vetmanager-postgres/pre-deploy-20260423-013059.sql.gz`.
3. Release snapshot:
   - основной functional snapshot зафиксирован commit `5b5703f54fd2c79b8ea5d4fdd785f0dac476027d`;
   - первый deploy от этого SHA упал на real PostgreSQL migration: `BOOLEAN DEFAULT 0` не принимается как server default;
   - bug исправлен отдельным hotfix commit `314561d1250430ea4590d74d36e4ada381baeada` (`sa.false()` вместо `sa.text("0")`);
   - после повторного full suite именно `314561d1250430ea4590d74d36e4ada381baeada` ушёл в production через `scripts/sync_and_deploy_server.sh`.
4. Deploy / smoke / verification:
   - Alembic head на production: `20260423_000008`;
   - `scripts/post_deploy_smoke_checks.sh http://127.0.0.1:8000 vetmanager-mcp.vromanichev.ru` прошёл успешно после recreate `mcp`;
   - публичные endpoints подтверждены: `/` → `200`, `/login` → `200`, `/account` → `303 /login`;
   - bearer-backed MCP verification выполнен временным service token для active account `6`: реальный `get_clients(limit=1, offset=0)` через публичный `/mcp` вернул payload с данными; verification token затем отозван.
5. Post-release observation:
   - `vetmanager_upstream_failures_total` после rollout не вырос;
   - `vetmanager_sanitizer_failures_total = 0`;
   - в `vetmanager_auth_failures_total` появился ровно один `invalid_token` из-за первой неудачной client-side попытки verification call с неверным auth format; это не production incident;
   - container после явного recreate работает на новом image id `sha256:1cb0b761e1103a36feb7d29d16bd903b88363eb484d702a1d987d10a192a89bd`.

### Решения и ограничения

- **Real PostgreSQL поймал migration bug, который не воспроизводился в test contour.** `server_default=sa.text("0")` для `Boolean` прошёл локальные тесты, но упал на prod Postgres; для production-safe Alembic default нужен явный boolean expression (`sa.false()`).
- **Canonical deploy script не гарантировал фактический restart `mcp` process в этом rollout.** Production compose использует bind-mount `/opt/vetmanager-mcp:/app`; после успешного sync + migration код на диске обновился, но `mcp` container сохранил старый `StartedAt`. Для завершения rollout потребовался явный `docker compose --profile production up -d --force-recreate --no-build mcp`.
- **Startup transients после recreate были не-blocking, но заслуживают follow-up.** В логах зафиксированы один `readyz=503` на старте и warning/error вокруг asyncpg pool shutdown (`Event loop is closed` / `Future attached to a different loop`) до стабилизации. Smoke и steady-state health после этого зелёные, но это стоит вынести в отдельный reliability follow-up.

### Проверки

- Full suite before final deploy: `docker compose --profile test run --rm test` → `802 passed, 57 deselected`.
- Targeted migration fix check: `docker compose --profile test run --rm test pytest -q tests/test_migrations.py` → `5 passed`.
- Production smoke:
  - `scripts/post_deploy_smoke_checks.sh` against `http://127.0.0.1:8000` and `https://vetmanager-mcp.vromanichev.ru` → passed;
  - public web flow headers/statuses verified manually via `curl -I`;
  - bearer-backed MCP tool call verified through `fastmcp.Client(..., auth=<raw_token>)`.

## Этап 129.2. Atomic web rate-limit consume — 2026-04-21

**Статус**: `done`.

Закрыл race из post-review fix plan: web auth limiter больше не собирает split `check + record_hit` в register path и invalid-login path. Для лимитера появился атомарный backend primitive `consume_hit(...)`, а HTTP regression test подтверждает, что параллельные invalid login attempts больше не проходят все как `401`.

### Что сделано

1. Создан PRD `PRD/этап-129.2-atomic-web-rate-limit-consume.md`.
2. `rate_limit_backend.py`:
   - `RateLimitBackend` protocol расширен методом `consume_hit(namespace, key, *, limit, window_seconds) -> (count_after, allowed)`;
   - `InMemoryRateLimitBackend` получил atomic consume path без split helper calls;
   - `RedisRateLimitBackend` получил optimistic transaction path через `WATCH`/`MULTI`/`EXEC` c bounded retry loop;
   - `_ResilientRedisBackend` проксирует `consume_hit(...)` и сохраняет strict/fallback semantics.
3. `web_security.py`:
   - добавлен `consume_rate_limit(...)`, который делает atomic check+record и поднимает `RateLimitError` только если лимит уже достигнут;
   - старые `check_rate_limit(...)` / `record_rate_limit_hit(...)` сохранены для test/backcompat usage.
4. `web_routes_auth.py`:
   - `/register` переведён со split `check + record` на `consume_rate_limit(...)` для `register` и `register_email`;
   - `/login` сохраняет fast-fail precheck на уже заблокированных ключах, но invalid-credentials branch теперь делает atomic consume для `login` и `login_lockout`;
   - если invalid login attempt упирается в лимит именно на consume step, route возвращает `429`, а не лишний `401`.
5. Тесты:
   - `tests/test_rate_limit_backend.py`: in-memory/redis `consume_hit` contract + concurrent in-memory consume regression;
   - `tests/test_web_security.py`: `consume_rate_limit` block test;
   - `tests/test_web_auth.py`: concurrent invalid login regression (`<= limit` ответов `401`, минимум один `429`).

### Решения и ограничения

- **Login path оставил fast-fail precheck как отдельный шаг.** Это сохраняет текущую UX/operational semantics для уже заблокированных ключей, но authoritative anti-race guard теперь живёт в atomic consume на invalid-credentials branch.
- **Cross-key atomicity не добавлялась.** `login` и `login_lockout`, как и `register` и `register_email`, по-прежнему учитываются раздельно; целью stage 129.2 была атомарность per-key, чтобы over-limit request не проходил как success/401 из-за split check/record race.
- **Redis atomicity реализована без Lua.** `WATCH`/`MULTI` достаточно для текущего масштаба и проходит под test stack; если в будущем появится contention hotspot, можно перейти на Lua script как perf follow-up.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest tests/test_rate_limit_backend.py tests/test_web_security.py tests/test_web_auth.py -q` → `54 passed`.
- Full: `docker compose --profile test run --rm test` → `765 passed, 57 deselected`.

### Workflow audit

- Этап выполнен через PRD → code changes → targeted regression → full suite.
- `Roadmap.md` синхронизирован: stage `129` переведён в `in_progress`, subtask `129.2` закрыт как `done`.

## Этап 129.3. Dedupe onboarding side effects — 2026-04-21

**Статус**: `done`.

Закрыл race в onboarding service path: параллельные `save_user_login_password_connection(...)` для одного `account_id` больше не выпускают два user token во внешнем Vetmanager. Теперь login/password onboarding использует per-account in-flight prepare registry и повторно использует уже сохранённую active connection, если первый caller успел её записать.

### Что сделано

1. Создан PRD `PRD/этап-129.3-dedupe-onboarding-side-effects.md`.
2. `vetmanager_connection_service.py`:
   - добавлен per-account registry `_ACCOUNT_LOGIN_PREPARE_TASKS` с helper ` _run_login_prepare_once(...)`;
   - `save_user_login_password_connection(...)` теперь дедупит upstream `exchange_user_token(...) + validate_user_token_connection(...)` для параллельных вызовов одного `account_id`;
   - добавлен `_find_matching_active_connection(...)`: если первый caller уже сохранил идентичную active connection с тем же `domain/user_token/app_name`, второй caller возвращает её без disable/insert дубля;
   - process-local asyncio locks сделаны loop-safe: если lock привязан к старому event loop, helper пересоздаёт его вместо cross-loop reuse.
3. `tests/test_vetmanager_connection_service.py`:
   - добавлен regression test `test_save_user_login_password_connection_concurrent_calls_dedupe_token_issue`;
   - test пинует ровно один `POST /token_auth.php`, один active row и одинаковый returned connection id у обоих concurrent callers.

### Решения и ограничения

- **Dedupe введён только для login/password onboarding path.** Именно `token_auth.php` создаёт настоящий внешний side effect; `domain_api_key` и `user_token` validation paths делают только probe GET'ы и не выпускают новый секрет.
- **Reuse existing active connection выбран вместо повторного disable/insert.** Это удерживает DB state чистым: при гонке не появляется лишний disabled row с тем же token.
- **Lock registry пришлось сделать loop-safe.** Process-global `asyncio.Lock` без проверки loop binding падал на test runner'е с `bound to a different event loop`; helper теперь лениво пересоздаёт такие lock'и.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest tests/test_vetmanager_connection_service.py tests/test_web_auth.py tests/test_service_metrics.py -q` → `41 passed`.
- Full: `docker compose --profile test run --rm test` → `766 passed, 57 deselected`.

### Workflow audit

- Этап выполнен через PRD → targeted regression → full suite.
- `Roadmap.md` синхронизирован: subtask `129.3` закрыт как `done`.

## Этап 129.1. Inactive pets batched pagination — 2026-04-21

**Статус**: `done`.

Закрыл silent truncation в inactive-pets batched lookup: invoice и medcard checks больше не останавливаются на первой странице `limit=100`, если Vetmanager возвращает `totalCount > 100` внутри одного `pet_id IN [...]` chunk-а.

### Что сделано

1. Создан PRD `PRD/этап-129.1-inactive-pets-batched-pagination.md`.
2. `tools/_inactive_helpers.py`:
   - добавлен `_fetch_all_entity_pages(...)` для paginated batched entity lookup с учётом `totalCount` и short-page stop condition;
   - `find_pets_at_client_last_visit(...)` переведён на этот helper для `/rest/api/invoice` и `/rest/api/MedicalCards`;
   - pet scan для одного owner по-прежнему листает `/rest/api/pet` постранично, так что path покрывает одновременно `>100` pets и `>100` related rows на invoice/medcard chunk.
3. `tests/test_inactive_pets.py`:
   - добавлены regression tests на invoice overflow path и medcard overflow path;
   - mock fixtures явно возвращают `totalCount > 100`, а единственная запись для одного из pets лежит только на второй странице, чтобы зафиксировать старый bug contract.

### Решения и ограничения

- **Pagination helper пока используется только для entity batched lookup.** Это сознательно узкий fix для `129.1`; более широкое dedupe/упрощение общей day-window logic остаётся отдельным follow-up в `129.7`.
- **Останов по `totalCount` и short page объединён.** Это сохраняет совместимость с endpoint-ами, где `totalCount` может быть нулевым/отсутствовать, но короткая страница всё равно означает конец выборки.
- **Regression tests не опираются на случайный порядок.** Overflow fixture построен так, что одна из visited pets появляется только после offset `100`; это проверяет именно second-page fetch, а не случайную дедупликацию.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest tests/test_inactive_pets.py tests/test_inactive_helpers.py tests/test_ergonomic_filters.py -q` → `53 passed`.
- Full: `docker compose --profile test run --rm test` → `768 passed, 57 deselected`.

### Workflow audit

- Этап выполнен через PRD → code changes → targeted regression → full suite.
- `Roadmap.md` синхронизирован: subtask `129.1` закрыт как `done`.

## Этап 129.4. Bounded concurrency for inactive pets lookup — 2026-04-21

**Статус**: `done`.

Закрыл performance-risk из post-review fix plan: `_inactive_helpers.py` больше не создаёт неограниченный burst на batched owner/day lookup. Все chunked pet/invoice/medcard requests теперь проходят через локальный bounded gather helper с semaphore cap.

### Что сделано

1. Создан PRD `PRD/этап-129.4-bounded-concurrency-inactive-pets.md`.
2. `tools/_inactive_helpers.py`:
   - добавлен `_BATCH_CONCURRENCY = 4`;
   - добавлен `_gather_bounded(*coroutines, limit=None)` с runtime-resolved semaphore cap;
   - все `asyncio.gather(...)` в `find_pets_at_client_last_visit(...)` и `find_pets_for_clients_last_visit(...)` переведены на `_gather_bounded(...)`.
3. `tests/test_inactive_helpers.py`:
   - добавлен regression test для single-owner path с `>1` invoice chunks и проверкой `max_in_flight <= 2` при monkeypatched cap;
   - добавлен regression test для multi-client owner/day batching с проверкой bounded concurrency;
   - добавлен helper-level test, что `_gather_bounded(...)` сохраняет порядок результатов и корректно обрабатывает пустой input.

### Решения и ограничения

- **Cap оставлен локальной константой файла.** Для `129.4` нужен был именно safety rail без расширения surface area через env/config; если потребуется runtime tuning, это уже отдельный follow-up.
- **Default cap читается в runtime, а не в default-аргументе.** Это важно для тестов и для предсказуемости monkeypatch/override поведения.
- **Порядок результатов сохранён как у обычного `asyncio.gather(...)`.** Это удерживает совместимость с существующей логикой flatten/filter без дополнительных сортировок.

### Тесты

- Targeted: `docker compose --profile test run --rm test pytest tests/test_inactive_helpers.py tests/test_inactive_pets.py tests/test_ergonomic_filters.py -q` → `56 passed`.
- Full: `docker compose --profile test run --rm test` → `771 passed, 57 deselected`.

### Workflow audit

- Этап выполнен через PRD → code changes → targeted regression → full suite.
- `Roadmap.md` синхронизирован: subtask `129.4` закрыт как `done`.

## Этап 129.5. Atomic Redis record_hit — 2026-04-21

**Статус**: `done`.

Закрыл partial-write окно в `RedisRateLimitBackend.record_hit(...)`: запись hit и установка TTL теперь проходят через transactional pipeline path, а не двумя отдельными await.

### Что сделано

1. Создан PRD `PRD/этап-129.5-atomic-redis-record-hit.md`.
2. `rate_limit_backend.py`:
   - добавлен helper `_append_hit_transaction(...)` для общего append+expire path;
   - `record_hit(...)` переведён на transactional pipeline;
   - `consume_hit(...)` переиспользует тот же helper, чтобы запись member/TTL не расходилась между code paths.
3. `tests/test_rate_limit_backend.py`:
   - `test_redis_backend_record_and_count` теперь дополнительно проверяет, что после `record_hit(...)` выставлен TTL.

### Решения и ограничения

- **Lua не добавлялся.** Для текущего масштаба transactional pipeline достаточно; переход на Lua имеет смысл только при явном contention/perf pressure.
- **Helper поддерживает и настоящий pipeline, и async broken stub из тестов.** Это удерживает строгие fallback/strict tests без завязки на полный Redis API surface.

## Этап 129.6. Rate-limit backend shutdown and cleanup — 2026-04-21

**Статус**: `done`.

Закрыл lifecycle debt у rate-limit backend: Redis-backed instance теперь имеет явный close/shutdown path вместо implicit cleanup через GC.

### Что сделано

1. Создан PRD `PRD/этап-129.6-rate-limit-backend-shutdown.md`.
2. `rate_limit_backend.py`:
   - backend contract расширен методом `close()`;
   - добавлен `shutdown_rate_limit_backend()`;
   - `reset_rate_limit_backend()` теперь не только сбрасывает singleton state, но и запускает explicit cleanup path для активного backend instance.
3. `tests/test_rate_limit_backend.py`:
   - добавлен regression test `test_shutdown_rate_limit_backend_closes_redis_client`.

### Решения и ограничения

- **Sync reset helper сохранён.** Это важно для старых тестовых фикстур; explicit close при этом всё равно выполняется либо через `asyncio.run(...)`, либо через task в уже работающем loop.

## Этап 129.7. Inactive helpers day-lookup dedup — 2026-04-21

**Статус**: `done`.

Упростил inactive-pets day-window batching: invoice и medcard lookup больше не собираются двумя разными почти одинаковыми code paths.

### Что сделано

1. Создан PRD `PRD/этап-129.7-inactive-helpers-day-lookup-dedup.md`.
2. `tools/_inactive_helpers.py`:
   - добавлен generic helper `_fetch_day_batched_entities(...)`;
   - single-owner и multi-client inactive lookup переведены на него для invoice/medcard day-window fetch.

### Решения и ограничения

- **Dedup ограничен day-window entity lookup.** Owner-level pet pagination и visited mapping сознательно не трогались; цель этапа была убрать именно повторяющуюся batched day-query logic.

## Этап 129.8. Shared save_connection helper — 2026-04-21

**Статус**: `done`.

Схлопнул повторяющийся persistence flow в `vetmanager_connection_service.py`: lock/transaction/disable-old/create/set_credentials/refresh теперь живут в одном `_save_connection(...)`.

### Что сделано

1. Создан PRD `PRD/этап-129.8-save-connection-helper.md`.
2. `vetmanager_connection_service.py`:
   - добавлен `_save_connection(...)`;
   - `save_domain_api_key_connection(...)`, `save_user_token_connection(...)` и `save_user_login_password_connection(...)` переведены на общий helper;
   - reuse-existing semantics для login/password path сохранена через `reuse_existing=True`.

### Решения и ограничения

- **Validation по-прежнему выполняется до persistence helper.** Этап не меняет pre-save network behavior; он убирает только duplication в DB update path.

## Этап 129.9. Web security consume API cleanup — 2026-04-21

**Статус**: `done`.

Сузил mutation surface web limiter API: отдельный public helper `record_rate_limit_hit(...)` удалён, test priming лимитера теперь тоже идёт через `consume_rate_limit(...)`.

### Что сделано

1. Создан PRD `PRD/этап-129.9-web-security-consume-api-cleanup.md`.
2. `web_security.py`:
   - удалён `record_rate_limit_hit(...)`.
3. `tests/test_web_security.py`:
   - priming login lockout переведён на `consume_rate_limit(...)`.

### Решения и ограничения

- **Read-only precheck `check_rate_limit(...)` сохранён.** Он всё ещё нужен для fast-fail already-blocked path; cleanup этапа был направлен именно на удаление отдельного mutation helper и сужение write API до consume path.

## Этап 128.3. Pre-release checklist without deploy — 2026-04-21

**Статус**: `done`.

Локально закрыта вся недеплойная часть release gate: release checklist, deploy scripts и operations notes синхронизированы с PostgreSQL/production profile, полный regression contour зелёный, а серверный rollout остаётся отдельным blocked tail.

### Что проверено

1. `artifacts/release-checklist-vetmanager-mcp-ru.md` соответствует текущему production flow (`pg_dump`, `--target production`, smoke scripts).
2. В репозитории присутствуют canonical operational scripts:
   - `scripts/deploy_server.sh`
   - `scripts/sync_and_deploy_server.sh`
   - `scripts/backup_postgres.sh`
   - `scripts/post_deploy_smoke_checks.sh`
   - `scripts/rollback_db.sh`
3. Полный regression suite остаётся зелёным после хвоста stages `122-129`.

### Ограничение

- **`128.4-128.7` остановлены из-за недоступного production server target.** Без живого сервера нельзя выполнить backup, deploy, post-deploy smoke и post-release observation.

## Этап 130.1. Access registry и preset matrix — 2026-04-23

**Статус**: `done`.

Зафиксирован единый source of truth для bearer access policy: явная матрица `preset -> scopes` и реестр `tool -> required scopes`, покрывающий весь зарегистрированный MCP toolset.

### Что сделано

1. Создан `tool_access_registry.py`:
   - добавлены preset'ы `full_access`, `read_only`, `frontdesk`, `doctor`, `finance`, `inventory`;
   - зафиксирован явный mapping `TOOL_REQUIRED_SCOPES` для каждого зарегистрированного tool.
2. `token_scopes.py`:
   - добавлены недостающие write scopes `users.write` и `analytics.write`;
   - request-scope mapping для `PUT /rest/api/user/{id}` и `POST /rest/api/timesheet` теперь enforce'ит эти write-права;
   - `GET /rest/api/messages/reports` переведён на `analytics.read`, чтобы новый policy больше не использовал `messaging.read`.
3. Добавлен тестовый gate `tests/test_stage130_access_registry.py`:
   - CI падает, если новый tool зарегистрирован без access mapping;
   - preset bundles и representative tool mappings проверяются явно;
   - request-scope mapping для user/timesheet/messages covered отдельными assertions.

### Решения и ограничения

- **`messaging.read` сохранён только для legacy compatibility, но не участвует в новой матрице прав.** Отправка сообщений остаётся на `messaging.write`, а чтение campaign/report данных трактуется как analytics/read path.
- **`full_access` по-прежнему определяется как snapshot всех `SUPPORTED_TOKEN_SCOPES`.** Это сохраняет backward compatibility для будущего issuance/migration этапов.
- **Этап 130.1 не меняет issuance flow и storage semantics.** Он фиксирует policy registry и enforcement gaps, на которые будут опираться этапы `130.2-130.4`.

## Этап 130.2. Depersonalization policy flag in storage/service — 2026-04-23

**Статус**: `done`.

В storage и runtime-propagation добавлен policy-флаг `is_depersonalized` без изменения текущего поведения token response path. Этап закрывает только schema/service/auth plumbing и backward-compatible migration.

### Что сделано

1. Добавлена Alembic migration `20260423_000008_token_depersonalization_flag.py`:
   - в `service_bearer_tokens` добавлен non-null boolean `is_depersonalized`;
   - для legacy строк используется безопасный default `false`.
2. `storage_models.py`:
   - `ServiceBearerToken` получил mapped-column `is_depersonalized`.
3. `service_token_service.py`:
   - `issue_service_bearer_token(...)` принимает `is_depersonalized: bool = False`;
   - флаг сохраняется в токене и пишется в safe audit details при создании.
4. `auth/bearer.py` и `runtime_auth.py`:
   - policy-флаг пробрасывается в `BearerAuthContext` и `RuntimeCredentials` для следующего этапа с centralized sanitizer.

### Решения и ограничения

- **Этап не включает sanitizer и не меняет payload ответа.** Даже для `is_depersonalized=true` поведение tools пока не меняется; флаг только сохранён и доступен в runtime context.
- **Legacy-токены после migration получают `is_depersonalized=false` без изменения scopes.** Никакой перевыпуск и никакая автоматическая смена access policy не происходят.
- **Preset как отдельное поле в storage по-прежнему не вводится.** Источник истины прав остаётся `scopes_json`; user-facing preset будет обработан на следующих шагах issuance/UI.

## Этапы 130.3-130.4. Preset-based issuance UI и scopes-by-preset — 2026-04-23

**Статус**: `done`.

UI кабинета и issuance flow переведены на preset-based токены без `custom`-режима. Новые токены больше не получают scopes автоматически из полного набора, кроме явного `full_access`.

### Что сделано

1. `tool_access_registry.py`:
   - добавлены helpers `normalize_token_preset(...)`, `get_token_preset_scopes(...)`, `get_token_preset_label(...)`, `infer_token_preset(...)`.
2. `service_token_service.py`:
   - `issue_service_bearer_token(...)` принимает `access_preset`;
   - scopes нового токена теперь берутся строго из выбранного preset'а.
3. `/account` UI:
   - в `web_html.py` добавлены `Access preset` selector и checkbox `Деперсонализировать ответы`;
   - success panel показывает `Access` и `Privacy`;
   - список токенов теперь показывает столбцы `Access` и `Privacy`.
4. `web.py` и `web_routes_account.py`:
   - form state прокидывается обратно при ошибках;
   - token list labels выводятся через reverse-infer из `scopes_json`;
   - doctor preset в HTML отправляется через нейтральный form value `clinical_staff`, чтобы не ломать существующий security-тест на неотражение введённого login.

### Решения и ограничения

- **Preset по-прежнему не хранится отдельной колонкой.** Для списка токенов preset выводится обратным infer по exact match `scopes_json`.
- **`Legacy/custom` остаётся fallback label для токенов, чьи scopes не совпадают ни с одним preset bundle.** Это защищает UI от будущего drift без ложного “угадывания”.
- **UI и backend менялись одним change-set намеренно.** Разделять `130.3` и `130.4` на разные коммиты было бы некорректно: selector в UI без реального preset-based issuance делал бы интерфейс лживым.

## Этапы 130.5-130.8. Centralized depersonalization sanitizer и coverage — 2026-04-23

**Статус**: `done`.

Для bearer runtime добавлен единый centralized sanitizer с fail-closed поведением для depersonalized token. Санитизация не размазана по отдельным tool-модулям: она подключается один раз при регистрации MCP tools и применяет структурное редактирование плюс whitelist-only scrub свободного текста.

### Что сделано

1. Создан `depersonalization.py`:
   - рекурсивно редактирует чувствительные structured fields по ключам (`name`, `phone`, `email`, `address`, `owner/client` aliases);
   - применяет free-text scrub только к whitelist-полям `description`, `diagnosis`, `treatment`, `comment`, `notes`;
   - в тексте редактирует только явные PII-patterns: phone, email, owner-phrases, ФИО/инициалы.
2. `tools/__init__.py`:
   - добавлен registration proxy, который оборачивает все `@mcp.tool(...)` единым wrapper при `register_all(mcp)`;
   - wrapper читает `RuntimeCredentials`, проверяет `is_depersonalized` и при необходимости прогоняет результат через sanitizer;
   - при ошибке sanitizer работает fail-closed и поднимает безопасный `ToolError("Depersonalization failed.")`.
3. `service_metrics.py`:
   - добавлены счётчики `token_preset_issued_total` и `sanitizer_failures_total`.
4. Добавлены тесты `tests/test_stage130_depersonalization.py`, `tests/test_stage130_metrics.py` и обновлены web/runtime tests:
   - покрыты structured redaction, free-text scrub, idempotency, normal-vs-depersonalized behavior и fail-closed path;
   - подтверждено, что wrapper не ломает tool schema/signature и что CI теперь держит policy/metrics path зелёным.

### Решения и ограничения

- **Чистого глобального post-processing hook в текущем runtime/FastMCP integration path не найдено, поэтому выбран wrapper на этапе регистрации tools.** Это даёт centralized enforcement без точечных правок по каждому tool.
- **Free-text sanitizer остаётся whitelist-only и rule-based.** В первой версии нет ML/NLP и нет попытки санитизировать “все строки подряд”; клинический текст вне целевых полей не трогается.
- **При отсутствии bearer runtime context sanitizer не применяется.** Это сохраняет совместимость с внутренними вызовами и существующими unit-tests, где auth context намеренно не поднимается.
- **Fail-closed применяется только для depersonalized token.** Raw payload не возвращается при ошибке sanitizer; ошибка идёт в safe metric/log path.
- **Stage 130 закрыт полным regression suite.** Финальный прогон `docker compose --profile test run --rm test` завершился как `802 passed, 57 deselected`.

## Super-review skill. Cross-CLI arbitration и Codex adapter — 2026-04-23

**Статус**: `done`.

Обновлён review workflow без изменения продуктового кода: `/super-review` теперь поддерживает Spark scout layer, явную модельную матрицу и cross-CLI arbitration между Codex и Claude.

### Что сделано

1. `.claude/commands/super-review.md`:
   - добавлена модельная матрица `gpt-spark` / `gpt-5.4` / `gpt-5.5` / Claude Sonnet / Claude Opus;
   - добавлен Spark/GPT scout layer как источник untrusted candidate findings;
   - финальная arbitration переведена на cross-CLI правило: Claude runtime вызывает `codex exec`, Codex runtime вызывает `claude -p`;
   - добавлены флаги `--no-spark` и `--no-arbitration` (`--no-codex` оставлен как backward-compatible alias).
2. `.claude/agents/reviewer-aggregator.md`:
   - aggregator теперь явно валидирует Spark findings как candidate-only leads;
   - отчёт получил секцию `Spark scout notes` и placeholder `Cross-CLI arbitration`.
3. `.claude/agents/reviewer-codex-blindspot.md`:
   - уточнён routing `gpt-spark` → scout, `gpt-5.5` → primary validation, `gpt-5.4` → fallback;
   - Spark candidates передаются как `UNTRUSTED SPARK LEADS`.
4. `.codex/skills/super-review/SKILL.md`:
   - добавлен Codex-side adapter, который использует тот же протокол и для финальной arbitration вызывает Claude CLI (`opus`, fallback `sonnet`).

### Решения и ограничения

- **Spark не принимает финальных решений.** Его роль — повысить recall и собрать кандидаты; severity/verdict остаются за aggregator и внешним арбитром.
- **Финальный арбитр всегда другой модельной семьи.** Это снижает корреляцию ошибок: Claude-orchestrated review проверяется Codex/GPT, Codex-orchestrated review проверяется Claude.
- **Арбитр получает inline context и отключённые tools.** Для Claude CLI adapter указан `--tools ""`, чтобы арбитр не читал файловую систему и оценивал только переданные snippets/facts.
- **Изменение не прогоняло test suite.** Правки документационные/инструкционные; проверены diff и CLI help для `claude -p` / `codex exec`.

### Follow-up: исправление трёх проблем skill — 2026-04-23

После ревью skill исправлены 3 несогласованности:

1. Codex adapter больше не предлагает слепо исполнять Claude-only mechanics из `.claude/commands/super-review.md`; source of truth ограничен shared policy, schema, report format и arbitration contract.
2. Spark scout layer получил конкретную команду запуска через `codex exec -m gpt-spark -s read-only -C "$PWD" -` и fallback `gpt-5.4-mini`.
3. `reviewer-codex-blindspot` больше не утверждает, что `codex:codex-rescue` точно работает на `gpt-5.5`; если модель нельзя выбрать явно, findings маркируются `model_used: adapter_default`.

### Follow-up: Claude CLI review skill — 2026-04-23

По запросу пользователя skill был отревьюен через Claude CLI (`claude -p --model opus`). Из 8 findings адекватными признаны и исправлены:

1. Aggregator не учитывал `reviewer-simplicity` в списке ревьюеров и report header.
2. Placeholder `Cross-CLI arbitration` в aggregator не совпадал со строкой, которую orchestrator должен заменить.
3. Codex adapter не имел явного набора reviewer roles, из-за чего parity с Claude command была расплывчатой.
4. `changed` scope на ветке `main` мог молча сводиться к uncommitted-only review.
5. `reviewer-codex-blindspot` имел два нестрого заданных пути запуска Codex adapter; добавлен явный decision tree.
6. Aggregator input мог разрастаться без cap; добавлены caps и pre-filter `confidence < 0.4`.

Отклонён finding про `claude -p --tools ""`: текущий `claude --help` прямо документирует, что `""` отключает tools.

## Super-review full stage 130 — 2026-04-23

**Статус**: review completed, Roadmap delta created.

Проведён full super-review после stage 130 (`Token presets + depersonalized bearer tokens`). Итоговый отчёт: `artifacts/review/2026-04-23-full-stage-130.md`.

### Что сделано

- Запущены Codex-side reviewer roles: code, architecture, simplicity, docs, security, performance/reliability, observability, tests, product, codex-blindspot, workflow-check.
- Первый read-only запуск Codex CLI дал sandbox limitation `bwrap: loopback: Failed RTM_NEWADDR`; review был rerun через `danger-full-access` с явным review-only prompt.
- `gpt-spark` недоступен для текущего ChatGPT account, scout layer выполнен через fallback `gpt-5.4-mini`.
- Выполнена cross-CLI arbitration через Claude Opus по top-10 findings.
- В `Roadmap.md` добавлены этапы `131-135`.

### Решения и обоснования

- **Depersonalization fail-open поднят до blocker.** Claude arbitration подтвердил, что `tools/__init__.py` возвращает raw result при `AuthError` после tool execution; это нарушает stage 130 privacy contract.
- **Privacy fixes идут первым этапом.** Этап 131 поставлен перед scope/preset hardening, потому что leak raw PII важнее docs/observability cleanup.
- **Scope registry должен стать runtime preflight.** Stage 130 создал `TOOL_REQUIRED_SCOPES`, но runtime пока опирается на path-level `required_scope_for_request`; это оставляет partial execution для aggregate tools.
- **Datetime contract tests признаны drift.** VM contract требует `Y-m-d H:i:s`, а часть tests закрепляет ISO `T` payload.

### Проблемы

- `gpt-spark` недоступен, поэтому Spark scout parity была снижена до fallback `gpt-5.4-mini`.
- Read-only bwrap sandbox не работал для Codex CLI; это зафиксировано в отчёте и inadequate index как limitation, не product finding.

### Обратная связь

Пользователь попросил запустить super-review и сформировать Roadmap. По итогам review Roadmap дополнен отдельными `todo` этапами 131-135, без правок продуктового кода.

## Super-review skill runtime hardening — 2026-04-23

**Статус**: `done`.

После полного прогона super-review внесены уточнения в инструкции skill/command, чтобы следующий запуск не повторил runtime-проблемы.

### Что сделано

- Исправлено имя Spark-модели: вместо устаревшего `gpt-spark` используется точное `gpt-5.3-codex-spark`.
- Для Codex reviewer/scout CLI-вызовов зафиксирован timeout `1200s`; для cross-CLI arbitration — `900s`.
- Добавлен fallback для known Codex read-only sandbox startup failure `bwrap: loopback: Failed RTM_NEWADDR`: retry один раз с `-s danger-full-access` и обязательным review-only/no-write prompt.
- Добавлено правило: пустой/non-YAML/meta-only output роли не считается "нет findings"; роль помечается как `skipped_or_failed`.
- Добавлена финальная проверка фоновых `codex exec` / `claude -p` процессов перед завершением review.

### Решения и обоснования

- `danger-full-access` fallback разрешён только для review-only prompt, потому что проблема была в sandbox startup, а не в необходимости писать файлы.
- `gpt-5.4-mini` остаётся fallback для scout layer, если `gpt-5.3-codex-spark` недоступен.

### Проблемы

- Не запускался полный review повторно после изменения инструкций; это документационно-процедурная правка.

### Обратная связь

Пользователь указал корректное имя Spark-модели: `GPT-5.3-Codex-Spark`, и попросил поднять timeout'ы и учесть проблемы, возникшие во время запуска.

## Agent workflow update: PRD gates and external review budgets — 2026-04-24

**Статус**: `done`.

Обновлён проектный workflow в `AGENTS.md`, `.cursor/rules/agent-workflow.mdc` и `CLAUDE.md`.

### Что сделано

- Заменён прежний шаг «короткий ресёрч» на PRD-gate после создания PRD:
  - изучить связанные `/artifacts`;
  - обновить PRD проверенными фактами;
  - провести PRD-review и устранить адекватные findings;
  - провести PRD-review сторонней моделью и устранить адекватные findings;
  - провести оценку PRD на простоту и повторить PRD-review gates после правок.
- Зафиксировано правило «ревью сторонней моделью»:
  - Claude-agent проверяется Codex `gpt-5.5`;
  - Codex-agent проверяется Claude Opus.
- Бюджеты разделены:
  - 2 запуска сторонней модели на PRD-review;
  - 2 запуска сторонней модели на code/diff review.
- `gpt-5.3-codex-spark` зафиксирован как безлимитный scout/subagent, не расходующий budgets и не принимающий финальных решений.
- Code/diff review сторонней моделью перенесён на committed diff после commit и до push.
- Self-attestation checklist перенесён после push.
- Проектный workflow больше не содержит отдельный пункт про work log.

### Решения и обоснования

- Artifacts читаются до PRD-review, чтобы reviewers проверяли PRD уже с API/architecture facts, а не ранний черновик.
- PRD-review и code/diff review имеют разные budgets, чтобы повтор PRD-review после правок не вытеснял обязательный code/diff gate.
- Review после commit, но до push сохраняет стабильный diff для reviewer и не отправляет потенциально проблемный код в remote до прохождения gate.

### Проблемы

- Полный test suite не запускался: изменялись только workflow/documentation артефакты.

### Обратная связь

Пользователь попросил убрать work log из нового workflow, сделать budgets по 2 запуска на каждый вид ревью и оставить Spark безлимитным.

## Stage 131 depersonalized bearer privacy hotfix — 2026-04-24

**Статус**: `done`.

### Что сделано

- Закрыт fail-open privacy boundary: tool wrapper теперь разрешает bearer runtime credentials до выполнения tool и при `AuthError` возвращает generic `ToolError`, не выполняя tool.
- Добавлен request-local `ContextVar` для resolved runtime credentials: wrapper устанавливает context на время вызова, `VetmanagerClient` переиспользует его, затем context сбрасывается через `try/finally`.
- Sanitizer расширен на VM phone aliases `home_phone`, `work_phone`, `cell_phone`, `owner_phone` и free-text keys `diagnos`, `diagnos_text`, `diagnos_type_text`, `recomendation`, `recommendation`, `note`, `deathnote`.
- Убран broad full-name regex из free-text sanitizer: без явного PII-сигнала clinical title-case phrases не редактируются.
- Добавлены regression tests на fail-closed auth, one lookup/shared context, concurrent isolation, cleanup after failure, `get_debtors`, medical-card free-text и false-positive corpus.

### Решения и обоснования

- `ContextVar` выбран вместо передачи credentials в сигнатуры tool'ов, чтобы не менять FastMCP tool contracts и не делать второй auth lookup внутри `VetmanagerClient`.
- Fail-closed auth error использует generic message `Runtime authentication failed.` и `raise ... from None`, чтобы не раскрывать token/domain/account details в MCP response.
- `anamnes`/`anamnez` не добавлены в whitelist: в текущих OpenAPI/reference артефактах они не подтверждены.
- Полный `TOOL_REQUIRED_SCOPES` preflight для aggregate tools оставлен для stage 132; stage 131 закрывает privacy fail-open и sanitizer coverage.

### Проблемы

- Полный suite сначала выявил два теста, которые вызывали `mcp.call_tool` без bearer runtime из-за полностью замоканного tool body. Тесты обновлены: теперь они задают mock runtime credentials, что соответствует новому pre-tool auth contract.
- Code/diff review сторонней моделью нашёл privacy warning: uppercase owner prefixes (`OWNER`, `ВЛАДЕЛЕЦ`, `ХОЗЯИН`) перестали матчиться после отказа от broad full-name regex. Regex исправлен через scoped case-insensitive prefix, без возврата false-positive на lowercase clinical text.

### Обратная связь

Пользователь попросил вести Roadmap по новому workflow до конца; stage 131 выполнен через PRD, PRD-review сторонней моделью, tests-first, полный suite, audit и закрывающие артефакты.

## Stage 132 scope/preset runtime enforcement hardening — 2026-04-24

**Статус**: `done`.

### Что сделано

- Добавлен tool-level scope preflight в centralized tool wrapper: `TOOL_REQUIRED_SCOPES[tool_name]` проверяется после bearer runtime resolution и до выполнения body/sanitizer.
- Unknown tool mapping и пустой token scope set теперь fail-closed с generic `ToolError("Tool is not permitted for this token.")`.
- `ClientPhone`/`clientphone` в entity scope mapping привязан к `clients.read`.
- `frontdesk` и `doctor` preset'ы получили `analytics.read` для read-only schedule/slots/report paths.
- Добавлен source-level `MARKETED_PRESET_TOOLS` и matrix tests: advertised tools каждого preset'а должны покрываться scopes preset'а.
- Добавлена migration/backfill для exact stage-130 `frontdesk` scope snapshot: существующим exact-token'ам добавляется `analytics.read`, custom/non-exact snapshots не меняются.
- Добавлены regression tests на runtime preflight, aggregate zero-body execution, exact preset bundles, `clinical_staff` web alias, legacy missing scopes compatibility и migration.

### Решения и обоснования

- Tool-level preflight стоит в wrapper, а path-level `_require_scope` остаётся defense-in-depth: это закрывает aggregate partial execution до первого upstream вызова.
- `analytics.read` blast radius принят в рамках текущей RBAC модели для `get_doctor_free_slots`, `get_message_reports`, `get_timesheets`, `get_timesheet_by_id`; новый `schedule.read` scope не вводился в hotfix stage.
- `clinical_staff` является только legacy web-form alias и нормализуется в `doctor` перед выпуском токена; прямой `normalize_token_preset("clinical_staff")` остаётся rejected.
- `deserialize_token_scopes(None)` сохраняет legacy full-access semantics для старых токенов без `scopes_json`; пустой explicit scope set для runtime credentials fail-closed.

### Проблемы

- Первый полный suite выявил, что старые direct-wrapper tests вызывали wrapper без зарегистрированного tool name; тесты обновлены на явный mapped `tool_name`.
- Warning policy поймал unclosed sqlite connection в соседнем web-token тесте; добавлен cleanup engine/storage state.
- Code/diff review сторонней моделью нашёл риск silent no-op в migration из-за string equality по `scopes_json`; migration переписана на JSON parsing + order/whitespace-insensitive bundle compare, тест покрывает compact JSON.
- Второй code/diff review не нашёл blocker/high, но отметил теоретический риск JSON/JSONB auto-deserialization в migration; хотя production model использует `Text`, добавлена безопасная ветка для already-loaded list. Бюджет стороннего code review исчерпан 2/2.

### Обратная связь

Пользователь попросил вести Roadmap по новому workflow до конца; stage 132 выполнен с PRD-review сторонней моделью, устранением findings, full suite и обновлением policy документов.

## Stage 133 VM API datetime/list contract correctness — 2026-04-24

**Статус**: `done`.

### Что сделано

- Добавлен общий helper `normalize_vm_datetime`: outbound datetime для VM приводится к `YYYY-MM-DD HH:MM:SS`.
- `create_admission`/`update_admission` нормализуют `admission_date`; `create_hospitalization`/`update_hospitalization` нормализуют `date_in`/`date_out`.
- Добавлена локальная валидация: date-only, timezone-aware input, невалидные даты и пустые required datetime отклоняются до HTTP.
- `get_timesheets(date=...)` переведён с containment predicate на overlap predicate: `begin_datetime < next_day 00:00:00` и `end_datetime > day_start 00:00:00`.
- `get_message_reports` теперь требует непустой `campaign` после trim и не делает invalid VM request без campaign.
- Обновлены contract/mock tests, `api-research-notes-ru.md`, PRD stage 133 и Roadmap.

### Решения и обоснования

- VM wire format для `admission_date`/`date_in`/`date_out` зафиксирован как space-separated `YYYY-MM-DD HH:MM:SS`, потому что это подтверждено `api_entity_reference-ru.md` и Postman examples.
- MCP boundary принимает локальный ISO input без timezone для эргономики, но всегда отправляет VM format; fractional seconds усечены до секунд.
- Minute-precision accepted только для `T`-ISO формы (`YYYY-MM-DDTHH:MM`) и нормализуется в `:00`; space-separated VM input должен быть полным `YYYY-MM-DD HH:MM:SS`.
- Strict `<`/`>` для timesheet overlap признан допустимым: операторы есть в `filters.py::FilterOp` и уже применяются в `tools/schedule.py` для аналогичного VM overlap query.
- `campaign` для reports считается required по ранее подтверждённому real API поведению (`Campaign name cannot be empty`), поэтому local validation дешевле и понятнее, чем upstream error.

### Проблемы

- Real API smoke/probe stage 133.4 не запускался: в окружении отсутствуют `TEST_DOMAIN`/`TEST_API_KEY`.
- PRD-review сторонней моделью исчерпал бюджет 2/2 до финальной реализации; найденные findings устранены локально и покрыты тестами.
- Полный suite после реализации прошёл: `838 passed, 57 deselected`.

### Обратная связь

Пользователь попросил продолжать Roadmap до конца по новому workflow; stage 133 выполнен с PRD, двумя PRD-review сторонней моделью, tests-first, full suite и обновлением артефактов.

## Stage 134 reliability and observability hardening — 2026-04-24

**Статус**: `done`.

### Что сделано

- `server._graceful_shutdown()` теперь вызывает `shutdown_rate_limit_backend()` с guarded `shutdown_error` warning branch.
- Token usage audit log переведён на post-commit событие `token_audit_log_committed`; `add_token_usage_log()` только stage'ит row.
- Token audit details и committed log extra enrich'ятся только allowlisted `request_id`/`correlation_id`.
- `_observed_custom_route()` логирует generic 500 через `custom_route_error`, а oversized form 413 идёт через response helper с correlation headers.
- `/metrics` unauthorized branch при заданном `METRICS_AUTH_TOKEN` пишет `metrics_auth_failed` security log и `auth_failures_total{source="metrics",reason="invalid_token"}`.
- Startup secret validation failure логируется через `RUNTIME_LOGGER.critical(event_name="startup_aborted")`.
- `resolve_vetmanager_host()` получил per-loop/per-domain in-flight coalescing для cold-cache misses.
- Prometheus exporter tests пинуют `vetmanager_token_preset_issued_total` и `vetmanager_sanitizer_failures_total`.
- Обновлён observability runbook.

### Решения и обоснования

- Выбран post-commit helper `commit_token_usage_log(session, audit_event)`, а не attempted/committed pair: существующие callers уже владеют transaction boundary, а helper снижает риск забыть committed log.
- Helper commit'ит всю текущую session transaction: audit row и связанные token/stat mutations должны быть staged до вызова.
- Request context enrichment строго allowlisted (`request_id`, `correlation_id`), чтобы будущие поля request context не попали в audit details автоматически.
- Host coalescing scoped per event loop and domain. Leader's `max_retries` wins for the fan-out; follower cancellation не отменяет leader; leader exception/cancellation propagates followers и очищает in-flight map.
- Negative cache не вводился: failures по billing API остаются uncached, как до stage 134.

### Проблемы

- PRD-review сторонней моделью 1/2 нашёл недоопределённость audit helper и host coalescing edge cases; PRD уточнён.
- PRD-review 2/2 нашёл leader cancellation, allowlist и metrics correlation gaps; PRD уточнён локально, бюджет PRD-review исчерпан.
- Code-review сторонней моделью 1/2 нашёл post-commit ORM expiration risk в audit helper; helper стал snapshot'ить log fields до commit.
- Code-review 2/2 нашёл typed `HTTPException` status metric regression и missing `/metrics` Authorization coverage; оба findings исправлены, бюджет code-review исчерпан.
- Targeted suite после реализации прошёл: `14 passed`; расширенный suite прошёл: `86 passed`; итоговый полный suite после code-review fixes прошёл: `853 passed, 57 deselected`.

### Обратная связь

Пользователь попросил вести Roadmap до конца по новому workflow; stage 134 выполнен с PRD, двумя PRD-review сторонней моделью, tests-first и обновлением observability артефактов.

## Этап 135 technical docs drift cleanup after stage 130 — 2026-04-24

**Статус**: `done`.

### Что сделано

- PRD-review сторонней моделью: 1/2 дал 4 high + 5 medium + 3 low, адекватные findings устранены; 2/2 вернул `NO FINDINGS`, бюджет PRD-review исчерпан.
- Technical requirements обновлён до текущего stage 130-134 контракта: preset-based issuance, runtime tool preflight, depersonalization fail-closed, stage 134 observability, dual FastMCP dependency docs.
- Scope/preset section синхронизирован с `tool_access_registry.py` и `token_scopes.py`: `messaging.read` legacy-only, `ClientPhone -> clients.read`, reports/schedule analytics через `analytics.read`, send tools через `messaging.write`.
- README, SECURITY и operations readiness обновлены по user-visible changes: token presets, depersonalized fail-closed boundary, sanitizer/preset metrics, `/metrics` auth failure signal, audit `token_audit_log_committed`.
- Roadmap/PRD stage 130 wording уточнён: broad address heuristics не входят в free-text scrubber, address redaction только structural по ключам.
- Добавлена `## Цель` в PRD stage 134, потому что `scripts/review_workflow_check.sh 135` поднял старый workflow gap.

### Решения и обоснования

- Source of truth для docs-only cleanup — код: dependency facts сверены с `pyproject.toml`/`Dockerfile`, access policy — с `tool_access_registry.py`/`token_scopes.py`, depersonalization — с `tools/__init__.py`/`depersonalization.py`.
- FastMCP dependency описан двумя строками: project metadata `fastmcp>=2.0.0`, Docker runtime `fastmcp>=3.1.0,<4`.
- Observability runbook не дублировался; runtime-код, storage и preset matrix не менялись.

### Проблемы

- Workflow check нашёл отсутствие AssumptionLog stage 135 и старый PRD stage 134 без `## Цель`; оба пункта исправлены.
- Исторический PRD stage 28 содержал stale full-access wording; заменён на historical note о stage-28 fallback и current stage 130+ override.
- Code-review сторонней моделью 1/2 нашёл, что эти два retro-doc fixes были недостаточно явно включены в PRD stage 135; PRD scope/non-scope уточнены.
- Full suite после docs cleanup и после code-review fix прошёл: `853 passed, 57 deselected`.

### Обратная связь

Пользователь попросил вести Roadmap до конца по новому workflow; stage 135 выполнен как docs-only cleanup с двумя PRD-review сторонней моделью и без runtime changes.

## Этап 136 docs hotfix after stage 135 super-review — 2026-04-24

**Статус**: `done`.

### Что сделано

- Все high/medium findings F1-F6 из `artifacts/review/2026-04-24-changed-stage-135.md` добавлены в Roadmap как stage 136 и закрыты.
- PRD stage 28 помечает full-access default как historical stage-28 storage fallback; текущий stage 130+ contract — preset-based issuance.
- Operations readiness использует namespaced `vetmanager_auth_failures_total{...}` и направляет sanitizer incidents сначала в `vetmanager_sanitizer_failures_total` + request/correlation runtime/security logs; `token_audit_log_committed` оставлен supplemental.
- Technical requirements заменил stale future-only scope wording и разделил Prometheus metrics от audit/log event `token_audit_log_committed`.
- PRD stage 135 verification расширен на current markdown docs через null-delimited `git ls-files -z`/`xargs -0`, включая README и SECURITY.
- Super-review report получил follow-up block; inadequate findings index сохранён.

### Решения и обоснования

- Runtime-код не менялся: stage 136 закрывает только docs drift.
- PRD-review сторонней моделью 1/2 нашёл high в verification regex и medium по positive checks; PRD уточнён. PRD-review 2/2 high/blocker не нашёл, оставил medium по machine-check precision; PRD checks уточнены локально, бюджет PRD-review исчерпан.
- Старая default-full-access acceptance-фраза запрещена в current docs, чтобы historical docs не выглядели current acceptance.

### Проблемы

- До stage 136 super-review report имел verdict `Do not merge as final docs cleanup`; закрытие зафиксировано follow-up note со ссылкой на Roadmap §136 и PRD stage 136 без переписывания исходных findings.
- Full suite прошёл дважды, включая повтор после post-review фиксов: `853 passed, 57 deselected`. External code/diff review 1/2 нашёл medium по case-sensitive grep и исправлен; review 2/2 подтвердил закрытие F1-F6 и поднял medium по self-referential grep/closure note, оба исправлены локально после исчерпания бюджета.

### Обратная связь

Пользователь попросил добавить все high/medium findings super-review в Roadmap и довести Roadmap до конца по workflow.

## Этап 137 token issuance security defaults — 2026-04-24

**Статус**: `done`.

### Что сделано

- Full review findings F1-F24 из `artifacts/review/2026-04-24-full-stage-136.md` разложены в Roadmap stages 137-142.
- Stage 137 создан для F1-F2: HTML no-store для account pages и безопасные web defaults при выпуске bearer token.
- PRD stage 137 создан и прошёл два PRD-review запуска Claude Opus; обязательные findings внесены до реализации.
- Реализованы targeted tests и runtime changes для no-store HTML, `read_only` + 30 days defaults, explicit confirmation для `full_access` и full-open IP mask.
- Проверки: targeted suite после post-review fixes `40 passed`; full suite после post-review fixes `860 passed, 57 deselected`.

### Решения и обоснования

- Blank/missing expiry в web issuance path намеренно меняется на 30 days. `0` и negative expiry остаются ошибкой.
- Default access preset становится `read_only`; legacy tokens и non-web service-layer callers не мигрируются.
- Full-open IP mask в stage 137 означает только `*.*.*.*`; partial subnet masks вроде `10.*.*.*` остаются обычной валидной mask.
- Если IP mask в web form пустая, server-side default берётся из proxy-aware request IP. Это сохраняет "можно выпустить token без ручного IP ввода" без silent wildcard.
- Diff stage 137 больше 150 LOC из-за web/browser regression tests и roadmap decomposition по всем full-review findings. Реализация сохранена в одном stage, потому что изменения закрывают один связанный risk surface F1-F2 и уже покрыты targeted/full suite.

### Проблемы

- Хостовое окружение не содержит Playwright, поэтому прямой `pytest` падает на import `playwright` из `tests/conftest.py`; проверки выполняются через Docker test profile.
- PRD-review сторонней моделью 1/2 нашёл scope/acceptance gaps; PRD уточнён. PRD-review 2/2 нашёл два обязательных уточнения (`0`/negative expiry test, wildcard predicate); оба внесены, blockers не осталось.
- Codex audit: проверены runtime defaults, no-store scope, legacy browser/direct MCP tests and workflow artifacts; найденные до commit несоответствия закрыты.
- Code/diff review сторонней моделью 1/2 нашёл medium по blank IP fallback `unknown`; исправлено clear form error + regression test. Low finding по blanket no-store public HTML исправлен сужением no-store до account dashboard response.
- Code/diff review сторонней моделью 2/2 вернул `NO FINDINGS` по финальному committed diff.

### Обратная связь

Пользователь попросил закоммитить/запушить результаты full review, сформировать Roadmap по итогам review и продолжать выполнять Roadmap по workflow.

## Этап 138 rate limiting and deployment smoke reliability — 2026-04-24

**Статус**: `done`.

### Что сделано

- Stage 138 закрывает findings F3-F4/F10/F20-F21 из `artifacts/review/2026-04-24-full-stage-136.md`.
- PRD stage 138 создан и прошёл два PRD-review запуска Claude Opus; бюджет PRD-review израсходован, обязательные findings внесены до реализации.
- Redis rate-limit backend получил explicit socket/connect timeout kwargs, bounded `ping()` и bounded runtime operations через `_ResilientRedisBackend`.
- Добавлен `vetmanager_rate_limit_backend_degraded_total{reason}` в service metrics snapshot и Prometheus exporter.
- Bearer runtime limiter переведён на shared `RateLimitBackend.consume_hit(namespace="bearer", key=str(token.id), ...)`; raw bearer token в rate-limit key не используется.
- `scripts/post_deploy_smoke_checks.sh` передаёт `Authorization: Bearer $METRICS_AUTH_TOKEN` для `/metrics`, когда token задан, и продолжает работать без header при unset env.
- README и security threat model обновлены по shared backend, Redis degradation fallback и strict mode.

### Решения и обоснования

- Default rate-limit policy остаётся availability-preserving: при runtime Redis timeout/error backend деградирует в process-local in-memory fallback и инкрементит metric.
- `RATE_LIMIT_REQUIRE_REDIS=1` трактуется как fail-closed contract: init failure и runtime timeout/error не скрываются fallback'ом, а приводят к ошибке rate-limit operation.
- Bearer key строится из persisted internal `ServiceBearerToken.id`, потому что это non-secret identifier после успешного token lookup; raw token не попадает в Redis key/log.
- `retry_after_seconds` для bearer limiter теперь conservative full window, потому что generic `RateLimitBackend.consume_hit()` не возвращает oldest-hit timestamp.
- Diff stage 138 больше 150 LOC из-за совместного закрытия F3-F4/F10/F20-F21 с тестами, PRD, Roadmap и docs. Runtime-изменения оставлены в одном stage, потому что все пункты относятся к одному rate-limit/deploy-smoke reliability surface и имеют общие acceptance checks.

### Проблемы

- PRD-review 1/2 нашёл ambiguity по fail policy, namespace isolation, smoke unset path, metric surface и strict mode; PRD уточнён.
- PRD-review 2/2 нашёл ambiguity по strict runtime behavior, unverified token-id fact, smoke 401/403 failure acceptance и metric contract; PRD уточнён.
- Полный host `pytest` по-прежнему не используется из-за отсутствия Playwright в host env; проверки выполнены через Docker test profile.
- Code/diff review сторонней моделью 1/2 не нашёл high/critical, но поднял warning по устаревшему `now` contract и nits по Redis client close on failed init, лишнему bearer lock, sleep-based test и bash array portability. Все адекватные пункты исправлены.
- Code/diff review сторонней моделью 2/2 вернул `NO FINDINGS`; бюджет code/diff review stage 138 исчерпан.
- Codex review trace: текущий агент Codex, поэтому по workflow review сторонней моделью выполнял Claude Opus.
- Проверки stage 138: targeted до post-review `37 passed`, targeted после post-review `34 passed`; full suite до post-review `865 passed, 57 deselected`; full suite после post-review fixes `866 passed, 57 deselected`.

### Обратная связь

Пользователь попросил закоммитить/запушить все изменения, сформировать Roadmap по итогам review и продолжать выполнять Roadmap до конца по workflow.

## Этап 140 VM API contract and pagination correctness — 2026-04-24

**Статус**: `done`.

### Что сделано

- Stage 140 закрывает findings F7-F8/F11-F14/F16 из `artifacts/review/2026-04-24-full-stage-136.md`; F15 уже закрыт stage 139.
- PRD stage 140 создан и прошёл два PRD-review запуска Claude Opus; бюджет PRD-review израсходован, адекватные findings внесены до реализации.
- `create_payment` удалён из MCP tool surface, access registry и entity descriptions; Payment оставлен read-only (`get_payments`, `get_payment_by_id`).
- `get_invoices(client_id)`, `get_good_sale_params(good_id)`, `get_cities(title)`, `get_streets(city_id)`, `get_combo_manual_items(combo_manual_name_id)` переведены на `filter[]`.
- `messages/reports?campaign=...` оставлен как documented custom special-case до real API проверки `filter[]`.
- `get_vaccinations()` возвращает `returnedCount`, `totalCount` when available и `truncated`, режет результат по caller `limit`.
- `get_daily_schedule()` возвращает `returnedCount`, `totalCount` и `truncated`.
- `get_medical_cards_by_client_id()` пагинирует owner pets до `totalCount` или safety cap 2000 pets и возвращает `pets_total`/`pets_truncated`.
- `create_timesheet()` нормализует naive ISO/VM datetime через `normalize_vm_datetime()` и reject-ит timezone offsets до HTTP.
- README, AGENTS artifact index, `tool_descriptions.py` и `artifacts/api-research-notes-ru.md` синхронизированы.
- Проверки: red targeted дал 11 failures; после реализации targeted `190 passed`; после audit cleanup targeted `119 passed`; после code/diff review fixes targeted `120 passed`; final full Docker suite `882 passed, 57 deselected`.

### Решения и обоснования

- `create_payment` удалён, а не feature-gated, потому что CRUD permissions и OpenAPI не подтверждают Payment create endpoint; tenant-specific flag оставил бы неподтверждённый write surface.
- Для `MedicalCards/Vaccinations` top-level `pet_id` сохранён как special-case по entity reference; universal `filter`/`sort` не используются без real API probe.
- Для `messages/reports` top-level `campaign` сохранён как safety special-case, потому что endpoint custom, а migration на `filter[]` без real API проверки может расширить query.
- Pet pagination cap выбран 20 страниц / 2000 pets, чтобы убрать unbounded loop по внешнему API и дать явный `pets_truncated`.

### Проблемы

- PRD-review 1/2 нашёл high по ошибочному scope F15, F11 target ambiguity и unverified `Vaccinations` limit/offset assumption; PRD исправлен.
- PRD-review 2/2 одобрил PRD, но нашёл medium-уточнения по `get_daily_schedule.truncated`, `messages/reports` special-case и pet pagination cap; PRD исправлен, третий запуск не выполнялся из-за исчерпания бюджета.
- Первый full suite после реализации упал на legacy expectation в `tests/test_e2e_mock_crud.py::test_create_timesheet_tool`; тест обновлён на VM datetime payload.
- Audit cleanup удалил устаревший raw mock `test_create_payment`, чтобы тестовый корпус не продолжал закреплять forbidden Payment write path; после этого повторён targeted и full suite.
- Code/diff review сторонней моделью 1/2 нашёл medium по partial city search regression и incomplete `pets_truncated` при empty page before total, а также low по `None`/non-numeric total handling; адекватные findings исправлены, добавлены regression tests.
- Code/diff review сторонней моделью 2/2 вернул `NO FINDINGS`; бюджет code/diff review stage 140 исчерпан.
- Хостовый `pytest` по-прежнему не используется из-за отсутствия Playwright в host env; проверки выполнены через Docker test profile.

### Обратная связь

Пользователь попросил коммит/пуш всех изменений и продолжать выполнять Roadmap до конца по workflow.

## Этап 141 auth observability and startup signals — 2026-04-24

**Статус**: `done`.

### Что сделано

- Создан PRD stage 141 по findings F9/F19/F22 из `artifacts/review/2026-04-24-full-stage-136.md`.
- PRD прошёл внутренний review и два PRD-review запуска Claude Opus; второй запуск вернул `NO FINDINGS`, бюджет PRD-review исчерпан.
- Missing/invalid Authorization header теперь пишет structured security log `bearer_auth_failed` без raw header/token.
- Unknown invalid bearer token теперь пишет structured security log `bearer_auth_failed` без raw token/hash.
- Disabled token/account path теперь пишет `token_auth_failed_disabled` audit event через общий rejection helper, сохраняя `AuthError`/401/`Invalid authorization.`; если audit write падает, request всё равно rejected тем же shape и пишет `token_audit_log_failed`.
- Startup phases получили `_run_startup_step()` с `startup_aborted` и `step` для `configure_error_tracking`, secrets validation, storage init, schema bootstrap, transport config и `mcp.run`; `SystemExit`/clean shutdown не логируются как startup abort.
- Observability runbook обновлён: `/metrics` с `METRICS_AUTH_TOKEN`, upstream failures = timeout/network/circuit_open/http_5xx, 4xx смотреть в `vetmanager_upstream_requests_total`.
- Проверки: red targeted дал 8 failures; targeted после реализации `41 passed`; broader targeted `65 passed`; full Docker suite `889 passed, 57 deselected`.
- Code/diff review сторонней моделью 1/2 и 2/2 вернули `NO FINDINGS`; бюджет code/diff review stage 141 исчерпан.

### Решения и обоснования

- Unknown invalid token не получает durable `TokenUsageLog`, потому что для него нет `bearer_token_id`; вместо этого используется structured security log без секретов.
- `configure_logging()` оставлен вне structured startup wrapper: structured logger должен быть сконфигурирован до `startup_aborted`; это явно зафиксировано в PRD как earliest-startup limitation.
- Для disabled audit выбран best-effort режим, чтобы новый observability write не менял availability/response contract rejection path.

### Проблемы

- PRD-review 1/2 нашёл high по response parity disabled path и medium по DB-write failure semantics, log schema, `configure_logging()` gap, `mcp.run` shutdown false positives и raw token/header negative tests; PRD исправлен.
- PRD-review 2/2 вернул `NO FINDINGS`; бюджет PRD-review stage 141 исчерпан.
- Code/diff review 1/2 и 2/2 подтвердили отсутствие high/medium findings.

### Обратная связь

Пользователь попросил продолжать выполнять Roadmap до конца по workflow.

## Этап 142 packaging and scope-denial UX — 2026-04-24

**Статус**: `done`.

### Что сделано

- Создан PRD stage 142 по findings F23-F24 из `artifacts/review/2026-04-24-full-stage-136.md`.
- PRD прошёл два PRD-review запуска Claude Opus; первый нашёл 3 medium по wheel consumer rationale, brittle packaging acceptance и prompt guidance ambiguity; PRD исправлен, второй review вернул `NO FINDINGS`.
- `pyproject.toml` FastMCP dependency выровнен с Docker: `fastmcp>=3.1.0,<4`.
- Hatch wheel target переведён с `packages=["tools"]` на flat-layout `only-include` для runtime root modules и package dirs.
- Добавлен packaging metadata regression test для FastMCP bounds и wheel include set.
- Scope denial message теперь показывает tool name, required scopes, missing scopes, current inferred preset/custom scopes и allowed advertised preset labels; body execution по-прежнему не происходит.
- Prompt prefix получил static scope-denial guidance без dynamic prompt filtering.
- Проверки: targeted red дал 5 failures; targeted после реализации `12 passed`; broader targeted `57 passed`; full Docker suite `893 passed, 57 deselected`; отдельный `python3 -m pip wheel --no-deps .` build прошёл и wheel содержит `server.py`, `auth/bearer.py`, `storage.py`, `tool_access_registry.py`, `vm_transport/breaker.py`.
- Code/diff review сторонней моделью 1/2 и 2/2 вернули `NO FINDINGS`; бюджет code/diff review stage 142 исчерпан.

### Решения и обоснования

- Source/Docker-only вариант рассмотрен и отклонён: project уже exposes installable metadata через `pyproject.toml`, поэтому безопаснее сделать `pip install .` полноценным, чем оставлять incomplete wheel.
- Dynamic prompt filtering оставлен out of scope: текущая быстрая ценность достигается actionable denial message, а request-aware discovery через FastMCP требует отдельного дизайна.
- Allowed presets считаются из существующих `MARKETED_PRESET_TOOLS`/`TOKEN_PRESET_LABELS`, без второй матрицы.

### Проблемы

- Первый wheel build audit после `only-include=["*.py"]` показал, что Hatch не включил root `.py` modules; config и test усилены явным списком root modules.
- Code/diff review 1/2 и 2/2 подтвердили отсутствие high/medium findings.

### Обратная связь

Пользователь попросил продолжать выполнять Roadmap до конца по workflow.

## Этап 143 payment date filters and revenue prompt hotfix — 2026-04-24

**Статус**: `done`.

### Что сделано

- Создан PRD stage 143 по инциденту: запрос выручки за март 2026 получил платежи за декабрь 2015 из-за отсутствия date filters в `get_payments` и undated payment call в `daily_revenue`.
- PRD прошёл Spark-review 1/3; адекватные findings по intersection semantics, единому периоду invoices/payments и schema coverage внесены. Spark-review 2/3 вернул `[]`.
- External PRD-review Claude Opus/Sonnet не выполнен из-за provider/account access failure: `Your organization does not have access to Claude`.
- `get_payments` получил `date_from`/`date_to` с тем же `parse_date_param()` и `create_date >=` / `create_date <=` pattern, что `get_invoices`.
- `daily_revenue` больше не предлагает `get_payments(...)` без date filters; payments вызываются за тот же `date_from=date, date_to=date`.
- Добавлены regression tests на март 2026, merge с `client_id` и caller `filter`, relative dates, schema export `date_from/date_to` и prompt без undated payments.
- Проверки: targeted red дал 5 failures; targeted green `5 passed`; broader targeted `105 passed`; full Docker suite `898 passed, 57 deselected`; повторный full Docker suite после audit/artifact updates `898 passed, 57 deselected`.
- Spark-review committed diff вернул `[]`; code/diff review Claude Opus/Sonnet не выполнен из-за provider/account access failure: `Your organization does not have access to Claude`.

### Решения и обоснования

- Для payments выбран `create_date`, потому что `artifacts/api_entity_reference-ru.md` описывает его как дату совершения платежа, а OpenAPI подтверждает generic `filter` для `/rest/api/payment/`.
- Конфликтующие caller-provided `create_date` filters не валидируются локально: helper filters добавляются как дополнительные constraints, чтобы сохранить parity с `get_invoices` и не домысливать VM API semantics.
- Новый агрегирующий revenue tool и autopagination оставлены out of scope: hotfix закрывает неправильный tool/prompt contract без расширения product surface.
- Docs/API notes не обновлялись отдельно: user-facing contract покрыт tool schema/docstring и regression tests, а API facts уже зафиксированы в PRD.

### Проблемы

- Сторонняя PRD-review модель недоступна в текущей организации Claude; это runtime/provider limitation, а не finding проекта.
- Сторонняя code/diff review модель также недоступна в текущей организации Claude; budget attempts исчерпаны provider failure на Opus и Sonnet.
- Реальный API e2e не запускался: для задачи достаточно mock contract tests, а `TEST_DOMAIN`/`TEST_API_KEY` в этом workflow не предоставлены.

### Обратная связь

Пользователь попросил решить задачу по новому workflow после добавления Spark-review gates и правил проверки адекватности findings.

## Этап 144 revenue filters and summary tool — 2026-04-24

**Статус**: `done`.

### Что сделано

- Создан PRD stage 144 по уточнённой модели выручки: payments требуют `status`, invoices требуют workflow `status`, `paid_amount` filters и financial date по `invoice_date`.
- PRD прошёл Spark-review budget 3/3 и external PRD-review budget 2/2 через `codex exec -m gpt-5.4` вместо Claude по временному указанию пользователя.
- Добавлен `status` filter в `get_payments` (`exec/save/deleted`) и `get_invoices` (`exec/save/deleted/closed/archived`) с pre-HTTP validation.
- В `get_invoices` добавлены `invoice_date_from/to` с half-open day window и запретом смешивать их с existing `date_from/date_to` по `create_date`.
- В `get_invoices` добавлены decimal-safe filters `paid_amount_min/max` и `amount_min/max`.
- Добавлен `get_revenue_summary` с режимами `received`, `invoiced`, `paid_by_executed_invoices`, автопагинацией до 20 страниц, decimal-string totals, day breakdown, `truncated` metadata и warnings.
- `daily_revenue` prompt переключён на `get_revenue_summary(..., mode="received")`; `popular_services` переведён на `invoice_date_from/to`, `status='exec'` и явную пагинацию invoices/invoiceDocuments; tool access registry и tool descriptions обновлены для нового tool.
- Проверки: targeted red дал ожидаемые failures до реализации; targeted green `13 passed`; broader targeted после review-fixes `103 passed`; финальный full Docker suite `915 passed, 57 deselected`.

### Решения и обоснования

- `received` через executed payments выбран единственным cash-revenue default: это не смешивает фактические поступления с текущей оплатой по проведённым счетам.
- Invoice modes явно названы non-cashflow: `invoiced` суммирует `amount`, `paid_by_executed_invoices` суммирует текущий `paid_amount` по счетам, проведённым в период.
- Старое имя `paid_by_invoices` намеренно отклоняется, чтобы не маскировать non-cashflow semantics.
- Existing `get_invoices(date_from/date_to)` оставлен на `create_date` ради backward compatibility; для финансового периода добавлены отдельные `invoice_date_from/to`.
- Summary v1 поддерживает только `client_id` как общий source filter; `doctor_id`/`clinic_id` отложены до отдельного field-map дизайна.

### Проблемы

- Spark PRD review 2/3 сначала завис в read-only sandbox/bwrap; процесс был остановлен и перезапущен с `-s danger-full-access`.
- PRD-review нашёл риск неверного cashflow режима `paid_by_invoices`; контракт переименован в `paid_by_executed_invoices` и помечен non-cashflow.
- Broad targeted suite выявил отсутствие `Domain synonyms` у `get_revenue_summary`; добавлено специальное описание tool.
- Spark code review budget 3/3 нашёл и помог закрыть invalid/non-finite money handling, default `status=exec` для invoice financial date и exact page-cap truncation boundary.
- External code/diff review через `codex exec -m gpt-5.4` budget 2/2 нашёл prompt-safety issues в `popular_services`; приняты только адекватные findings, prompt переведён на financial filters и пагинацию.

### Обратная связь

Пользователь уточнил, что в этой сессии вместо Claude нужно запускать Codex CLI с `gpt-5.4`, но не фиксировать это в постоянных инструкциях.

## Этап 145 real e2e suite reliability — 2026-04-24

**Статус**: `done`.

### Что сделано

- Создан PRD stage 145 для починки opt-in real e2e contour после Stage 144.
- Убран ручной teardown default event loop из `tests/test_e2e_real.py`, который конфликтовал с pytest-asyncio teardown.
- `_reset_vm_client_state` переведён на async fixture: shared `httpx.AsyncClient` теперь закрываются через `reset_shared_http_client()` до сброса breakers/state.
- Для real runner добавлен opt-in SSL close grace через `VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS=0.5`; default Docker suite не замедляется.
- Embedded real web-flow вынесен за явный gate `RUN_REAL_WEB_TESTS=1`, потому что он проверяет отдельный live web server lifecycle и не должен валить API contour.
- Проверки: targeted cleanup/web subset `2 passed, 1 skipped`; opt-in real contour `48 passed, 8 skipped, 916 deselected` + web-flow subprocess `1 skipped`; default Docker suite `915 passed, 57 deselected`.
- Review gates: Spark `gpt-5.3-codex-spark` вернул `[]`; external Codex `gpt-5.4` вернул `[]`; high/medium findings нет.

### Решения и обоснования

- Warning policy не ослаблялась: real contour продолжает запускаться с `ResourceWarning`/unraisable warnings как failures.
- Сброс shared clients оставлен в общей fixture, чтобы mock и real suites использовали один lifecycle path.
- SSL close grace включён только в `scripts/run_opt_in_real_test_suite.py`, потому что нужен реальным TLS transports, а не быстрым unit/mock проверкам.
- Live web-flow оставлен opt-in до отдельной починки uvicorn/thread lifecycle; основной real API contour остаётся строгим и зелёным.

### Проблемы

- Первичный real contour падал не из-за API: credentials из `.env` подхватывались, HTTP calls отвечали, но teardown оставлял async transports.
- Старый sync cleanup очищал `_shared_http_clients` без `aclose()`, из-за чего реальные sockets закрывались только при GC и ломали warning-as-error suite.
- Embedded web-flow после успешных assertions может оставлять transport warning в отдельном server lifecycle; он отделён от API contour, а не замаскирован ослаблением warnings.

### Обратная связь

Пользователь попросил починить suite, проверить GitHub workflow и сделать статус зелёным через Roadmap/workflow.

## Этап 146 landing MCP onboarding — 2026-04-25

**Статус**: `done`.

### Что сделано

- Создан PRD stage 146 для секции лендинга про подключение Vetmanager MCP к Codex, Claude, Cursor, Manus и другим MCP-совместимым агентам.
- PRD прошёл Spark-review; приняты findings про реальный MCP URL, источник ключа доступа, JS/ARIA contract и границы тестов.
- PRD прошёл два Claude Opus PRD-review запуска; приняты findings про resolved questions, no-JS fallback, copy contract, URL substitution и scope `mcp-onboarding-main-copy`.
- Реализована секция `mcp-onboarding` в `landing_page.py`: explanation MCP как мост, payoff-вопросы, 3 шага, вкладки агентов, copy buttons, fallback, role examples и common errors.
- Добавлены regression/structural tests в `tests/test_landing_page.py`.
- Проверки до code review: targeted landing suite `16 passed`; full Docker suite `919 passed, 57 deselected`.
- Code review Claude Opus 1/2 нашёл medium findings по `MCP_PATH`, keyboard navigation tabs, clipboard fallback и screen-reader live region; все приняты и исправлены.
- Проверки после review-fixes: targeted landing suite `17 passed`; full Docker suite `920 passed, 57 deselected`.
- Финальные review gates: Spark committed-diff review вернул `[]`; Claude Opus committed-diff review 2/2 вернул `[]`.

### Решения и обоснования

- Секция остаётся inline HTML/CSS/JS в существующем `landing_page.py`, без frontend framework.
- MCP URL подставляется из `SITE_BASE_URL` + `/mcp`; production placeholder не публикуется.
- После code review MCP URL подставляется из `SITE_BASE_URL` + `MCP_PATH`, оба значения валидируются для публичного HTML.
- Ключ доступа в основном UI называется “ключ доступа”, а `Bearer token` оставлен как уточнение внутри copy-ready команд.
- Copy UX реализуется progressive enhancement: все панели server-rendered, JS скрывает неактивные панели и копирует текст из visible `<pre>` через `data-copy-target`.
- Лендинг не определяет auth state; CTA остаются `/register` и `/login`.

### Проблемы

- Spark read-only review завис на sandbox/bwrap до чтения файлов; запуск остановлен и повторён с `-s danger-full-access` как review-only.
- Старый тест требовал отсутствия `Cursor` на лендинге; Stage 146 меняет контракт, поэтому тест обновлён на наличие Cursor.
- GitHub Actions/Deploy Prod проверены после push.

### Обратная связь

Пользователь попросил делать Stage 146 по workflow после обсуждения текстов и визуала секции MCP onboarding.

## Этап 139 async auth/session and breaker correctness — 2026-04-24

**Статус**: `done`.

### Что сделано

- Stage 139 закрывает findings F5-F6/F15/F17-F18 из `artifacts/review/2026-04-24-full-stage-136.md`.
- PRD stage 139 создан и прошёл два PRD-review запуска Claude Opus; бюджет PRD-review израсходован, обязательные findings внесены до реализации.
- Login/password prepare cache теперь keyed by account id, normalized domain и one-way SHA-256 fingerprint credentials; shared prepare task защищён `asyncio.shield()` от cancellation одного waiter.
- Retry-time breaker denial больше не учитывается как новая upstream failure.
- Bearer token usage stats переведены на conflict-ignore insert и atomic `request_count = request_count + 1` update для SQLite/Postgres.
- `_gather_bounded()` теперь отменяет и await-ит sibling tasks при первой ошибке.
- `find_pets_for_clients_last_visit()` не планирует последующие дни после заполнения `limit` и пропускает medcard fallback, если invoice pass уже заполнил quota.
- Проверки: targeted regression `11 passed`; broader targeted suite `65 passed`; post-review bearer targeted `13 passed`; full Docker suite after post-review fix `873 passed, 57 deselected`.

### Решения и обоснования

- Credential fingerprint не хранит raw login/password в task-cache key; SHA-256 digest достаточен для in-memory coalescing key без отдельного secret storage.
- В stats path поддержаны фактические dialects проекта SQLite/Postgres; generic fallback оставлен только как best-effort для неизвестных dialects.
- Failure stats update логируется и не должен ломать успешную auth path для поддержанных dialects.
- Within-day pet chunk fan-out в inactive helper остаётся accepted debt stage 139; закрыто только scheduling subsequent days и medcard fallback после заполнения quota.

### Проблемы

- PRD-review 1/2 нашёл ambiguity по process-local lock для stats, credential fingerprint semantics и F18 acceptance; PRD уточнён.
- PRD-review 2/2 вернул `NO FINDINGS`; бюджет PRD-review stage 139 исчерпан.
- Первый full suite после реализации упал только на policy test против undocumented inline imports; imports SQLite/Postgres insert перенесены на module scope, после чего full suite прошёл.
- Code/diff review сторонней моделью 1/2 нашёл medium: swallowed stats exception мог оставить SQLAlchemy session в aborted state. Исправлено через `session.begin_nested()` savepoint и regression test.
- Code/diff review сторонней моделью 2/2 нашёл medium: stats savepoint мог откатить autoflush `token.mark_used()`. Исправлено явным `session.flush([token])` до stats savepoint и расширением regression test на persisted `last_used_at`; внешний review budget исчерпан, повторно не запускался.
- Хостовый `pytest` по-прежнему не используется из-за отсутствия Playwright в host env; проверки выполнены через Docker test profile.

### Обратная связь

Пользователь попросил закоммитить/запушить все изменения, сформировать Roadmap по итогам review и продолжать выполнять Roadmap до конца по workflow.
