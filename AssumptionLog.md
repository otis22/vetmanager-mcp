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
