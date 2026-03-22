# AssumptionLog

Журнал допущений, неясностей и архитектурных решений по проекту vetmanager-mcp.

---

## Этап 1–2: Каркас и MCP-инструменты

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

**Итого:** 75 MCP-инструментов + 20 MCP-промптов.

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
