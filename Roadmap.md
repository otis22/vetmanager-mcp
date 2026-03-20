# Roadmap

Статусы: `todo` | `in_progress` | `done`

## Этап 1. Базовый каркас сервиса (по PRD) — `done`

- 1.1 Создать каркас проекта и точку входа MCP-сервера — `done`
- 1.2 Реализовать приём `domain` и `api_key` от пользователя в каждом запросе (без глобальной привязки к одному домену) — `done`
- 1.3 Реализовать клиент Vetmanager API с динамическим определением базового URL — `done`
- 1.4 Добавить обработку ошибок API/timeout и структурное логирование — `done`
- 1.5 Проверить, что конфигурация не захардкожена и сервер работает с разными доменами/ключами между запросами — `done`
- 1.6 Зафиксировать docker-only workflow: никаких запусков Python/CLI на хосте — `done`

## Этап 2. MCP-инструменты по сущностям (после Этапа 1) — `done`

- 2.1 Инструменты для `Client` — `done`
- 2.2 Инструменты для `Pet` — `done`
- 2.3 Инструменты для `Admission` — `done`
- 2.4 Инструменты для `MedicalCard` — `done`
- 2.5 Инструменты для `Invoice` — `done`
- 2.6 Инструменты для `Good` — `done`
- 2.7 Инструменты для `User` — `done`

## Этап 2.5. Расширение MCP-инструментов: остальные сущности (после Этапа 2) — `done`

### 2.5.1 Справочные сущности — `done`

- 2.5.1.1 `Breed` — породы животных — `done`
- 2.5.1.2 `PetType` — виды животных — `done`
- 2.5.1.3 `City` — города — `done`
- 2.5.1.4 `CityType` — типы населённых пунктов — `done`
- 2.5.1.5 `Street` — улицы — `done`
- 2.5.1.6 `Unit` — единицы измерения — `done`
- 2.5.1.7 `Role` — роли пользователей — `done`
- 2.5.1.8 `UserPosition` — должности персонала — `done`
- 2.5.1.9 `ComboManualName` — названия справочников — `done`
- 2.5.1.10 `ComboManualItem` — элементы справочников — `done`

### 2.5.2 Финансовые сущности — `done`

- 2.5.2.1 `Payment` — оплаты клиентов — `done`
- 2.5.2.2 `ClosingOfInvoices` — закрытие счетов — `done`
- 2.5.2.3 `InvoiceDocument` — позиции счёта — `done`
- 2.5.2.4 `Cassa` — кассы — `done`
- 2.5.2.5 `CassaClose` — закрытие касс — `done`

### 2.5.3 Складские сущности — `done`

- 2.5.3.1 `GoodGroup` — группы товаров — `done`
- 2.5.3.2 `GoodSaleParam` — параметры продажи товара — `done`
- 2.5.3.3 `PartyAccount` — партии товаров — `done`
- 2.5.3.4 `PartyAccountDoc` — документы партий — `done`
- 2.5.3.5 `StoreDocument` — складские документы — `done`
- 2.5.3.6 `Suppliers` — поставщики/контрагенты — `done`

### 2.5.4 Клинические сущности — `done`

- 2.5.4.1 `Hospital` — госпитализации — `done`
- 2.5.4.2 `HospitalBlock` — блоки стационара — `done`
- 2.5.4.3 `Diagnoses` — справочник диагнозов — `done`

### 2.5.5 Операционные сущности — `done`

- 2.5.5.1 `Clinics` — клиники/филиалы — `done`
- 2.5.5.2 `Timesheet` — рабочие графики сотрудников — `done`
- 2.5.5.3 `Properties` — системные свойства — `done`
- 2.5.5.4 `AnonymousClient` — анонимные клиенты — `done`

---

## Этап 2.6. MCP Prompts (после Этапа 2) — `done`

### 2.6.1 Промпты для администратора — `done`

- 2.6.1.1 `daily-schedule` — Расписание приёмов на день — `done`
- 2.6.1.2 `find-client` — Быстрый поиск клиента по имени или телефону — `done`
- 2.6.1.3 `client-balance` — Баланс и задолженность клиента — `done`
- 2.6.1.4 `book-appointment` — Запись на приём — `done`
- 2.6.1.5 `create-invoice` — Создание счёта — `done`
- 2.6.1.6 `doctor-workload` — Нагрузка и расписание врача за период — `done`
- 2.6.1.7 `unconfirmed-appointments` — Неподтверждённые записи на ближайшие 2 дня — `done`

### 2.6.2 Промпты для врача — `done`

- 2.6.2.1 `pet-history` — История болезни питомца (последние N записей) — `done`
- 2.6.2.2 `last-vaccinations` — Статус вакцинации питомца — `done`
- 2.6.2.3 `add-medical-note` — Добавить запись в медицинскую карту — `done`
- 2.6.2.4 `current-inpatients` — Пациенты в стационаре — `done`
- 2.6.2.5 `pet-invoices` — История счетов питомца — `done`
- 2.6.2.6 `pet-full-profile` — Полный профиль питомца: баланс клиента, дата последнего визита, последняя вакцинация, последние 3 медзаписи и содержимое последних 3 счетов — `done`

### 2.6.3 Финансовые промпты — `done`

- 2.6.3.1 `daily-revenue` — Выручка за день с разбивкой по врачам — `done`
- 2.6.3.2 `unpaid-invoices` — Все неоплаченные и частично оплаченные счета — `done`
- 2.6.3.3 `popular-services` — Топ-10 услуг и товаров по количеству и выручке за период — `done`

### 2.6.4 Промпты по складу и клиентской базе — `done`

- 2.6.4.1 `search-good` — Поиск товара или услуги в прайс-листе — `done`
- 2.6.4.2 `low-stock` — Товары с низким остатком на складе — `done`
- 2.6.4.3 `new-clients` — Клиенты, зарегистрированные за последние N дней — `done`
- 2.6.4.4 `client-no-visit` — Клиенты без визитов более 365 дней — `done`

---

## Этап 3. Локальное окружение через Docker Compose (после Этапа 2.5) — `done`

- 3.1 Добавить `docker-compose.yml` для локального запуска — `done`
- 3.2 Добавить `.env.example` только для локального/dev режима (не как единственный источник домена/ключа) — `done`
- 3.3 Проверить запуск и остановку через `docker compose up -d` / `docker compose down` — `done`
- 3.4 Добавить команды запуска CLI/тестов только через `docker compose exec/run` — `done`
- 3.5 Настроить запуск контейнеров с UID/GID хоста и non-root пользователем — `done`
- 3.6 Проверить, что изменения файлов из контейнера не ломают права на хосте — `done`

## Этап 4. Тестирование (после Этапа 3) — `done`

- 4.1 Добавить unit-тесты для конфигурации и API-клиента — `done`
- 4.2 Добавить e2e mock/contract-тесты по `artifacts/vetmanager_openapi_v6.json` — `done`
- 4.3 Добавить e2e real API тесты для домена `devtr6` (фиксированный тестовый стенд) — `done`
- 4.4 Обеспечить минимум 20 e2e-сценариев суммарно (mock/contract + real API) — `done` (37 passed)

## Этап 5. CI/CD и политика секретов (после Этапа 4) — `done`

- 5.1 Настроить запуск unit и e2e (где применимо) в CI — `done`
- 5.2 Хранить API-ключи только в локальном `.env` и CI secrets (без коммита в репозиторий) — `done`
- 5.3 Зафиксировать, что `devtr6` и тестовый ключ используются только для тестов — `done`
- 5.4 Проверить отсутствие доменов/ключей в исходниках и логах — `done`

## Этап 6. Операционные скрипты — `done`

- 6.1 Написать `scripts/init_server.sh` для первичной настройки сервера по `ssh user@host` (предусловие: `ssh-copy-id` настроен) — `done`
- 6.2 Написать `scripts/deploy_server.sh` для деплоя обновлений по `ssh user@host` — `done`
- 6.3 Добавить инструкцию запуска init/deploy скриптов и проверку smoke после деплоя — `done`
- 6.4 Перевести init/deploy на Docker-only выполнение (без Python на хосте) — `done`

## Этап 8. Защита от ошибок: лимиты на массовые операции (после Этапа 7) — `done`

Цель: предотвратить случайные массовые изменения данных из-за ошибочных промптов пользователя.

### Лимиты

| Операция | Ограничение | Поведение при нарушении |
|----------|-------------|-------------------------|
| `get_*` list — параметр `limit` | ≤ 100 | `ValueError` с подсказкой использовать пагинацию |
| `get_*` list — параметр `offset` | ≤ 10 000 | `ValueError` |
| `create_payment` — параметр `amount` | > 0 и ≤ 1 000 000 | `ValueError` (защита от ввода суммы в копейках) |

Принцип: `create_*`, `update_*`, `delete_*` всегда работают ровно с 1 записью (by ID или один POST) — это уже обеспечено архитектурой.

### Подзадачи

- 8.1 Добавить валидационную функцию `validate_list_params(limit, offset)` в отдельный `validators.py` — `done`
- 8.2 Применить валидацию `limit`/`offset` во всех `get_*` list-инструментах через единый вызов — `done`
- 8.3 Добавить валидацию `amount > 0 and amount <= 1_000_000` в `create_payment` — `done`
- 8.4 Написать unit-тесты на граничные значения лимитов — `done` (21 passed)
- 8.5 Зафиксировать решение в `AssumptionLog.md` — `done`

---

## Этап 7. Аудит полноты реализации (финальный этап, после Этапа 6) — `done`

- 7.1 Сверить все сущности из `artifacts/api_entity_reference-ru.md` и `artifacts/vetmanager_openapi_v6.json` со списком реализованных MCP-инструментов — выявить пропуски — `done`
- 7.2 Сверить доступные операции API (GET list, GET by id, POST, PUT, DELETE) по каждой сущности с реализованными инструментами — выявить недостающие операции — `done`
- 7.3 Реализовать недостающие сущности и операции, выявленные в п. 7.1–7.2 — `done` (добавлены update_pet, update_admission, update_medical_card)
- 7.4 Убедиться, что все инструменты покрыты тестами (unit + e2e) — `done` (37 passed)
- 7.5 Зафиксировать итоговую матрицу покрытия (сущность × операция) в `AssumptionLog.md` — `done`

---

## Этап 9. Локальный prod-like MCP через localhost (после Этапа 8) — `done`

Цель: подключать Cursor к MCP как к отдельному хосту (`localhost`), как в будущей публичной схеме.

- 9.1 Перевести сервер на HTTP transport для локального host-based подключения (`localhost`) — `done`
- 9.2 Настроить `docker-compose` с портом и переменными окружения для дефолтных credentials — `done`
- 9.3 Добавить fallback credentials (`VETMANAGER_DOMAIN`/`VETMANAGER_API_KEY`) при пустых параметрах инструмента — `done`
- 9.4 Обновить Cursor MCP config на host-based подключение (`http://localhost:8000/mcp`) — `done`
- 9.5 Проверить сценарий «топ-5 должников» через MCP и зафиксировать результат — `done`

---

## Этап 10. Variant A: конфигурация credentials через `mcp.json` headers (документация и задачи) — `done`

Цель: зафиксировать целевую схему, где `domain`/`api_key` приходят из клиентского `mcp.json` (`url` + `headers`), а в проекте хранятся только тестовые credentials для e2e.

- 10.1 Зафиксировать в Roadmap целевой формат `~/.cursor/mcp.json` (Variant A: `url` + `headers`) — `done`
- 10.2 Зафиксировать правило: runtime credentials не хранятся в репозитории и не задаются проектным `.env` для рабочего контура — `done`
- 10.3 Зафиксировать правило: `TEST_DOMAIN`/`TEST_API_KEY` используются только в e2e real tests — `done`
- 10.4 Создать PRD-задачу этапа 10 с декомпозицией (без кодовых работ в этом проходе) — `done`
- 10.5 Добавить отдельную задачу на обновление `README.md` под Variant A (пример `mcp.json`, границы тестового контура) — `done`
- 10.6 Проверить согласованность формулировок между `Roadmap.md`, `artifacts/prd-vetmanager-mcp-ru.md` и PRD-задачами этапа 10 — `done`

### Зафиксированные правила Variant A

Целевой формат `~/.cursor/mcp.json` для подключения к серверу:

```json
{
  "mcpServers": {
    "vetmanager": {
      "url": "http://<host>:8000/mcp",
      "headers": {
        "X-VM-Domain": "<clinic-subdomain>",
        "X-VM-Api-Key": "<rest-api-key>"
      }
    }
  }
}
```

Правила:
- Runtime credentials (`domain`/`api_key`) **не хранятся** в репозитории и не задаются в проектном `.env` в рабочем контуре.
- Каждый пользователь приносит свои credentials через `headers` в `mcp.json`.
- `TEST_DOMAIN`/`TEST_API_KEY` используются **только** в e2e real tests и задаются через локальный `.env` или CI secrets.

## Этап 11. Реализация Variant A: код, тесты, README — `done`

Цель: реализовать поддержку credentials через HTTP headers в MCP-сервере (Variant A).

- 11.1 Убрать env-fallback для runtime credentials из `VetmanagerClient` — `done`
- 11.2 Добавить чтение `X-VM-Domain` и `X-VM-Api-Key` из HTTP headers (`request_credentials.py`) — `done`
- 11.3 Убрать `VETMANAGER_DOMAIN`/`VETMANAGER_API_KEY` из runtime-окружения `docker-compose.yml` и `.env.example` — `done`
- 11.4 Обновить `vetmanager_client.py`: без env-fallback; при пустых credentials — явная ошибка — `done`
- 11.5 Обновить инструкции и description в `server.py` под Variant A — `done`
- 11.6 Написать/обновить тесты: без credentials → ошибка; с credentials в args → OK; `TEST_*` только в real e2e — `done` (107 passed)
- 11.7 Обновить `README.md`: пример `mcp.json` с headers, правила тестового контура — `done`
- 11.8 Зафиксировать решение в `AssumptionLog.md` — `done`

---

## Этап 12. Headers-only и security hardening (после Этапа 11) — `done`

Цель: перейти на строгий runtime-контракт только через HTTP headers, удалить `domain`/`api_key` из сигнатур инструментов, усилить безопасность и добавить pacing исходящих HTTP-запросов к Vetmanager API.

- 12.1 Обновить Workplan/PRD-артефакты под headers-only контракт (включая `artifacts/prd-vetmanager-mcp-ru.md`) — `done`
- 12.2 Перевести инструменты на сигнатуры без `domain`/`api_key` (breaking change для старых клиентов) — `done`
- 12.3 Обновить `VetmanagerClient`: credentials только из headers, 50ms wait между HTTP-запросами, сетевой retry/timeout hardening — `done`
- 12.4 Внедрить security-ограничения: строгая валидация `domain`, HTTPS + allowlist для резолвленного host, маскирование секретов в ошибках/логах — `done`
- 12.5 Обновить/починить тесты (unit + e2e mock + e2e real) под новый контракт — `done`
- 12.6 Обновить README и зафиксировать решения в `AssumptionLog.md` — `done`

---

## Этап 13. In-memory тегированный кеш GET (после Этапа 12) — `done`

Цель: добавить кеширование GET-запросов к Vetmanager API с TTL 15 минут, ключом `method + full_url_with_query + api_key_hash` и теговой инвалидацией на мутациях.

- 13.1 Обновить Workplan/PRD-артефакты под кеш-контракт (включая `artifacts/prd-vetmanager-mcp-ru.md`) — `done`
- 13.2 Добавить/обновить unit-тесты кеша (cache hit, TTL expiry, key isolation по `api_key_hash`, теговая инвалидация) — `done`
- 13.3 Реализовать in-memory хранилище кеша (`dict` + индекс тегов) с TTL 900s и `asyncio.Lock` — `done`
- 13.4 Интегрировать кеш в `VetmanagerClient`: GET read/write, POST/PUT/DELETE invalidation по тегу `domain:entity` — `done`
- 13.5 Обновить README и зафиксировать решения в `AssumptionLog.md` — `done`

---

## Этап 14. Универсальная фильтрация и сортировка в GET (после Этапа 13) — `done`

Цель: добавить унифицированную поддержку `sort`/`filter` во всех list `get_*` инструментах и покрыть новые возможности unit/e2e тестами.

- 14.1 Обновить Workplan/PRD-артефакты под контракт `sort`/`filter` (включая `artifacts/prd-vetmanager-mcp-ru.md`) — `done`
- 14.2 Добавить unit-тесты сериализации/валидации параметров `sort`/`filter` — `done`
- 14.3 Обновить e2e mock/real тесты для новых сценариев `sort`/`filter` — `done`
- 14.4 Реализовать общий helper построения list-параметров и применить ко всем list `get_*` — `done`
- 14.5 Проверить новые возможности вручную через MCP как внешний агент — `done`
- 14.6 Обновить README/AssumptionLog, закрыть этап 14, выполнить commit+push — `done`

---

## Этап 15. Профили клиента и питомца (после Этапа 14) — `done`

Цель: добавить два агрегирующих MCP-инструмента, которые за один вызов возвращают полный профиль клиента или питомца.

### 15.1 get_client_profile

- 15.1.1 Реализовать `get_client_profile(client_id)` в `tools/client.py` — `done`
  - Данные клиента (`get_client_by_id`)
  - Последние 5 счетов с `invoiceDocuments` и `payment_status` (filter by `client_id`, sort DESC by `id`)
  - Последние 5 приёмов (filter by `client_id`, sort DESC by `admission_date`)
  - Следующий назначенный приём (filter `status=active`, sort ASC by `admission_date`, limit 1)

### 15.2 get_pet_profile

- 15.2.1 Реализовать `get_vaccinations(pet_id)` в `tools/medical_card.py` — `done`
  - Эндпоинт: `GET /rest/api/MedicalCards/Vaccinations?pet_id={id}`
  - Возвращает все записи о вакцинациях питомца с полями `date`, `date_nexttime`, `name`
- 15.2.2 Реализовать `get_pet_profile(pet_id)` в `tools/pet.py` — `done`
  - Данные питомца (`get_pet_by_id`)
  - Последние 5 медицинских карт с диагнозами (filter by `pet_id`, sort DESC)
  - Вакцинации: дата последней и дата следующей ревакцинации (через `get_vaccinations`)

### 15.3 Тесты и документация

- 15.3.1 Добавить unit/mock тесты для `get_vaccinations`, `get_client_profile`, `get_pet_profile` — `done`
- 15.3.2 Зафиксировать решения в `AssumptionLog.md`, commit+push — `done`

---

## Этап 15.4. MCP Prompts: переход на headers-only контракт — `done`

Цель: привести MCP prompts в соответствие с текущим runtime-контрактом проекта, где credentials передаются только через HTTP headers, а не как аргументы prompt-функций.

- 15.4.1 Убрать `domain`/`api_key` из сигнатур всех prompt-функций в `prompts.py` — `done`
- 15.4.2 Убрать из текстов prompts инструкции вида `Use domain=...` / `api_key=...` и заменить их на headers-only формулировки — `done`
- 15.4.3 Обновить docstrings prompts под текущий контракт и фактические tool names/параметры — `done`
- 15.4.4 Добавить тест/проверку: prompts не требуют runtime credentials в аргументах и не подсказывают передавать их в tool calls — `done`
- 15.4.5 Обновить `README.md` и зафиксировать решение в `AssumptionLog.md` — `done`

---

## Этап 15.5. Синхронизация технических артефактов с текущей архитектурой — `todo`

Цель: устранить рассинхрон между кодом и справочными артефактами, чтобы дальнейшее планирование и реализация опирались на актуальную архитектуру проекта.

- 15.5.1 Обновить `artifacts/technical-requirements-vetmanager-mcp-ru.md` под текущую схему: headers-only credentials, HTTP transport, актуальная структура проекта и docker-only workflow — `todo`
- 15.5.2 Проверить согласованность `artifacts/technical-requirements-vetmanager-mcp-ru.md` с `README.md`, `Roadmap.md` и `artifacts/prd-vetmanager-mcp-ru.md` — `todo`
- 15.5.3 Зафиксировать обновлённые архитектурные решения в `AssumptionLog.md` — `todo`

---

## Этап 16. tools/list: полный ответ по спецификации MCP — `todo`

Цель: чтобы клиенты (в т.ч. vetmanager-ai-assistant) могли получать от сервера полный список возможностей с описаниями и схемами параметров, без хардкода на своей стороне.

- 16.1 Проверить, что ответ `tools/list` содержит для каждого инструмента поля по спецификации MCP: `name`, `description`, `inputSchema` (и при необходимости `title`) — `todo`
- 16.2 При необходимости доработать FastMCP/регистрацию инструментов так, чтобы в ответе были осмысленные `description` (из docstring) и `inputSchema` (типы и описание аргументов) — `todo`
- 16.3 Добавить тест или e2e-проверку: вызов `tools/list` возвращает не только имена, но и непустые `description` и `inputSchema` хотя бы для одного инструмента — `todo`
- 16.4 Зафиксировать контракт в README (раздел MCP-инструменты или отдельный подраздел про tools/list) — `todo`

---

## Этап 17. Лимиты в inputSchema (limit 1–100) — `done`

Цель: в ответе `tools/list` у всех инструментов с параметром `limit` в inputSchema были minimum=1, maximum=100 и описание, чтобы клиенты MCP и LLM не передавали невалидные значения.

- 17.1 Константы и тип `LimitParam` в validators, экспорт в schema — `done`
- 17.2 Заменить `limit: int = ...` на `limit: LimitParam = ...` во всех get_* в tools/*.py — `done`
- 17.3 Тест/проверка: tools/list возвращает у limit minimum=1, maximum=100 — `done`
- 17.4 AssumptionLog, README при необходимости — `done`

## Этап 18. Применить Справочник сущностей Vetmanager API — Доменные имена и синонимы(Архив скачан)


## Этап 19. Добавить эти методы

curl --location 'https://devtr6.vetmanager2.ru/rest/api/messages/all' \
--header 'X-REST-API-KEY: 600e562402f47b4f24ebca4f02331783' \
--data '{
    "message": "Rest post",
    "campaign": "All1"
}'

Response: 

{
    "success": true,
    "message": "Messages successfully sent to 21 users"
}


curl --location 'https://devtr6.vetmanager2.ru/rest/api/messages/users' \
--header 'X-REST-API-KEY: 600e562402f47b4f24ebca4f02331783' \
--data '{
    "message": "Rest post",
    "campaign": "Concrete1",
    "user_ids":[1]
}'

Response: 

{
    "success": true,
    "message": "Messages successfully sent to 21 users"
}


curl --location '/rest/api/messages/reports?campaign=All%20users' \
--header 'X-REST-API-KEY: {{API Key}}'

Ответ: 

{
    "success": true,
    "data": {
        "campaign": "All users",
        "total": 0,
        "sent": 0,
        "pending": 0
    }
}


curl --location 'https://devtr6.vetmanager2.ru/rest/api/messages/roles' \
--header 'X-REST-API-KEY: 600e562402f47b4f24ebca4f02331783' \
--header 'Content-Type: text/plain' \
--data '{
    "message": "Rest post",
    "campaign": "Concrete1",
    "roles": ["Врач"]
}'

Ответ: 

{
    "success": true,
    "message": "Messages successfully sent to 2 users with the specified roles"
}
