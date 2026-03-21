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
