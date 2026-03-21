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
