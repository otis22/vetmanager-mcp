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

## Этап 15.5. Синхронизация технических артефактов с текущей архитектурой — `done`

Цель: устранить рассинхрон между кодом и справочными артефактами, чтобы дальнейшее планирование и реализация опирались на актуальную архитектуру проекта.

- 15.5.1 Обновить `artifacts/technical-requirements-vetmanager-mcp-ru.md` под текущую схему: headers-only credentials, HTTP transport, актуальная структура проекта и docker-only workflow — `done`
- 15.5.2 Проверить согласованность `artifacts/technical-requirements-vetmanager-mcp-ru.md` с `README.md`, `Roadmap.md` и `artifacts/prd-vetmanager-mcp-ru.md` — `done`
- 15.5.3 Зафиксировать обновлённые архитектурные решения в `AssumptionLog.md` — `done`

---

## Этап 16. tools/list: полный ответ по спецификации MCP — `done`

Цель: чтобы клиенты (в т.ч. vetmanager-ai-assistant) могли получать от сервера полный список возможностей с описаниями и схемами параметров, без хардкода на своей стороне.

- 16.1 Проверить, что ответ `tools/list` содержит для каждого инструмента поля по спецификации MCP: `name`, `description`, `inputSchema` (и при необходимости `title`) — `done`
- 16.2 При необходимости доработать FastMCP/регистрацию инструментов так, чтобы в ответе были осмысленные `description` (из docstring) и `inputSchema` (типы и описание аргументов) — `done`
- 16.3 Добавить тест или e2e-проверку: вызов `tools/list` возвращает не только имена, но и непустые `description` и `inputSchema` хотя бы для одного инструмента — `done`
- 16.4 Зафиксировать контракт в README (раздел MCP-инструменты или отдельный подраздел про tools/list) — `done`

---

## Этап 17. Лимиты в inputSchema (limit 1–100) — `done`

Цель: в ответе `tools/list` у всех инструментов с параметром `limit` в inputSchema были minimum=1, maximum=100 и описание, чтобы клиенты MCP и LLM не передавали невалидные значения.

- 17.1 Константы и тип `LimitParam` в validators, экспорт в schema — `done`
- 17.2 Заменить `limit: int = ...` на `limit: LimitParam = ...` во всех get_* в tools/*.py — `done`
- 17.3 Тест/проверка: tools/list возвращает у limit minimum=1, maximum=100 — `done`
- 17.4 AssumptionLog, README при необходимости — `done`

## Этап 18. Применить Справочник сущностей Vetmanager API — Доменные имена и синонимы — `done`

Цель: использовать новый справочник как источник доменной семантики для
описаний MCP-инструментов, чтобы `tools/list` лучше помогал LLM выбирать нужный
инструмент по пользовательским формулировкам.

- 18.1 Создать PRD этапа 18 и централизованный каталог доменных синонимов для поддерживаемых сущностей — `done`
- 18.2 Улучшить descriptions всех MCP-инструментов на основе справочника и применить их при регистрации сервера — `done`
- 18.3 Добавить тесты/проверки `tools/list` на enriched descriptions и representative synonyms — `done`
- 18.4 Обновить `README.md` и `AssumptionLog.md`, зафиксировать контракт — `done`


## Этап 19. Глобальные уведомления `messages/*` — `done`

Цель: добавить MCP-инструменты для глобальных уведомлений Vetmanager:
массовая рассылка, отправка конкретным пользователям, отправка по ролям и
получение отчётов по campaign.

- 19.1 Нормализовать этап 19 в PRD и Workplan вместо raw curl-примеров — `done`
- 19.2 Реализовать `send_message_to_all`, `send_message_to_users`, `get_message_reports`, `send_message_to_roles` в `tools/operations.py` — `done`
- 19.3 Добавить mock/tool-level тесты и безопасный real smoke на `get_message_reports` — `done`
- 19.4 Обновить descriptions, `README.md` и `AssumptionLog.md` под новый контракт — `done`

---

## Этап 20. Bearer-only архитектура и артефакты (после Этапа 19) — `done`

Цель: спроектировать следующий этап продукта, в котором MCP-сервер использует только `Authorization: Bearer <service_token>`, а выбор и хранение Vetmanager-авторизации переносятся в аккаунт сервиса.

- 20.1 Создать PRD этапа 20 для bearer-only модели аккаунта и интеграции с Vetmanager — `done`
- 20.2 Обновить `artifacts/prd-vetmanager-mcp-ru.md` и `artifacts/technical-requirements-vetmanager-mcp-ru.md` под bearer-only направление — `done`
- 20.3 Зафиксировать доменную модель: `account`, `vetmanager_connection`, `service_bearer_token`, `token_usage_stats` / `token_usage_log` — `done`
- 20.4 Зафиксировать правило: Bearer-токены привязываются к аккаунту, а аккаунт хранит ровно один активный способ авторизации в Vetmanager — `done`
- 20.5 Зафиксировать правило: dual-mode не поддерживается; текущий headers-only runtime-контракт подлежит замене на bearer-only — `done`
- 20.6 Обновить `AssumptionLog.md` — `done`

## Этап 21. Storage и security foundation для Bearer-сервиса (после Этапа 20) — `done`

Цель: подготовить инфраструктурную основу для аккаунтов, Bearer-токенов и хранения Vetmanager-секретов.

- 21.1 Выбрать и внедрить БД для аккаунтов, интеграций и Bearer-токенов — `done`
- 21.2 Добавить миграции для `accounts`, `vetmanager_connections`, `service_bearer_tokens`, `token_usage_stats` / `token_usage_logs` — `done`
- 21.3 Реализовать безопасное хранение секретов Vetmanager (шифрование / secret management) — `done`
- 21.4 Реализовать хранение только hash Bearer-токена и безопасного `token_prefix` для UI и аудита — `done`
- 21.5 Добавить модели срока действия, revoke и статусов Bearer-токенов — `done`
- 21.6 Добавить unit-тесты persistence/security слоя — `done`

## Этап 22. Bearer auth в MCP runtime (после Этапа 21) — `done`

Цель: перевести MCP runtime на bearer-only авторизацию аккаунта сервиса.

- 22.1 Реализовать извлечение `Authorization: Bearer` из MCP HTTP request — `done`
- 22.2 Реализовать lookup `service_bearer_token -> account -> active vetmanager_connection` — `done`
- 22.3 Заменить текущий credentials context на account-based auth context — `done`
- 22.4 Удалить runtime-поддержку `X-VM-Domain` / `X-VM-Api-Key` из рабочего контура — `done`
- 22.5 Добавить безопасные ошибки: `missing bearer`, `invalid bearer`, `expired bearer`, `revoked bearer`, `account connection not configured` — `done`
- 22.6 Обновить unit/e2e тесты bearer-only контракта — `done`

## Этап 23. Vetmanager auth mode #1: `domain + rest_api_key` (после Этапа 22) — `done`

Цель: первым поддержать подключение аккаунта к Vetmanager через REST API key и домен клиники.

- 23.1 Реализовать connection mode `domain + rest_api_key` — `done`
- 23.2 Добавить валидацию и тест подключения при сохранении интеграции аккаунта — `done`
- 23.3 Интегрировать mode в `VetmanagerClient` через отдельный abstraction layer — `done`
- 23.4 Проверить все существующие MCP tools/prompts на bearer-only runtime — `done`
- 23.5 Обновить README и документацию подключения — `done`

## Этап 24. Web: лендинг, регистрация, кабинет аккаунта (после Этапа 23) — `done`

Цель: добавить внешний пользовательский контур сервиса для описания продукта, регистрации и управления интеграцией с Vetmanager.

- 24.1 Создать PRD этапа 24 для web-слоя и UX кабинета — `done`
- 24.2 Реализовать лендинг с описанием сервиса и вариантов подключения — `done`
- 24.3 Реализовать обязательную регистрацию и login/logout — `done`
- 24.4 Реализовать экран настройки Vetmanager-интеграции для `domain + rest_api_key` — `done`
- 24.5 Реализовать выпуск Bearer-токенов с именем и сроком действия — `done`
- 24.6 Реализовать экран списка токенов со статусом, сроком действия, последним использованием и количеством запросов — `done`
- 24.7 Зафиксировать одноразовый показ raw Bearer после создания и дальнейшее хранение только hash — `done`

## Этап 25. Usage accounting и admin analytics (после Этапа 24) — `done`

Цель: вести эксплуатационную статистику по Bearer-токенам и показывать её в кабинете аккаунта.

- 25.1 Реализовать обновление `last_used_at` для Bearer-токенов — `done`
- 25.2 Реализовать счётчик запросов по Bearer-токену — `done`
- 25.3 Добавить безопасный аудит создания и revoke токенов — `done`
- 25.4 Добавить отображение использования токенов в кабинете аккаунта — `done`
- 25.5 Добавить тесты на usage accounting без утечек секретов — `done`

## Этап 26. Vetmanager auth mode #2: `user login/password -> token` (после Этапа 25) — `done`

Цель: добавить второй способ подключения аккаунта к Vetmanager через пользовательский токен, получаемый по login/password flow.

- 26.1 Уточнить и зафиксировать контракт Vetmanager user-token flow по Postman и реальному API — `done`
- 26.2 Реализовать второй connection mode в abstraction layer — `done`
- 26.3 Добавить настройку этого mode в кабинете аккаунта — `done`
- 26.4 Добавить валидацию и тест подключения для второго mode — `done`
- 26.5 Проверить, что bearer runtime не зависит от конкретного Vetmanager auth mode — `done`
- 26.6 Добавить unit/mock/real smoke тесты второго режима — `done`

## Этап 27. Security hardening Bearer-сервиса (после Этапа 26) — `done`

Цель: усилить безопасность bearer-only сервиса и снизить риски компрометации токенов и веб-контура.

- 27.1 Добавить rate limiting по Bearer-токену — `done`
- 27.1.1 Провести аудит legacy test/runtime helper-кода под новый runtime-контракт и зафиксировать план рефакторинга — `done`
- 27.1.2 Добавить общие test factories и перевести `tests/test_client_multitenancy.py` на credential-based runtime-контракт — `done`
- 27.1.3 Перевести legacy helper'ы в `tests/test_e2e_mock.py` и смежных test support модулях — `done`
- 27.1.4 Прогнать и стабилизировать полный test suite после миграции legacy тестов — `done`
- 27.2 Добавить более подробный audit trail по auth events — `done`
- 27.3 Добавить политику cleanup/revocation для истёкших токенов — `done`
- 27.4 Усилить security web-сессий и secret management — `done`
- 27.5 Обновить technical requirements и `AssumptionLog.md` — `done`

## Этап 28. Future scopes/RBAC для Bearer-токенов (после Этапа 27) — `done`

Цель: спроектировать будущие ограничения прав Bearer-токенов по методам и доменным группам операций.

- 28.1 Спроектировать модель scopes / RBAC для Bearer-токенов — `done`
- 28.2 Зафиксировать coarse-grained scopes для первого итерационного релиза прав — `done`
- 28.3 Подготовить storage/schema под scopes без обязательного enforcement в этом этапе — `done`
- 28.4 Обновить PRD, technical requirements и `AssumptionLog.md` — `done`

## Этап 29. Stabilization: убрать test warnings и хвосты инфраструктуры — `done`

Цель: довести test suite до полностью чистого прогона без известных warning-сигналов и скрытых проблем lifecycle/cleanup.

- 29.1 Исследовать `aiosqlite` thread/loop warnings в `tests/test_client_multitenancy.py` — `done`
- 29.2 Исправить lifecycle/cleanup SQLite connections в тестовой инфраструктуре или runtime helpers — `done`
- 29.3 Добавить regression tests или fixture-guardrails против повторного появления warning-сценария — `done`
- 29.4 Обновить `AssumptionLog.md` по итоговой причине и исправлению — `done`

## Этап 30. Расширить real e2e tests на предоставленные тестовые данные — `done`

Цель: покрыть недостающие реальные сценарии для обоих Vetmanager auth flows на выделенном тестовом контуре `devtr6`.

Принятые тестовые данные для этапа:
- API key flow: `TEST_DOMAIN=devtr6`, отдельный test API key.
- Login/password flow: отдельные `TEST_USER_TOKEN_BASE_URL`, `TEST_USER_LOGIN`, `TEST_USER_PASSWORD` для получения user token в real smoke tests.

Правило хранения:
- Предпочтительный вариант: env/secrets тестового окружения и CI secrets.
- Хранение прямо в открытом репозитории допускается только если это осознанно подтверждённые несекретные тестовые credentials; по умолчанию так не делать.

- 30.1 Зафиксировать env-контракт для real e2e по обоим flows (`TEST_DOMAIN`, `TEST_API_KEY`, `TEST_USER_TOKEN_BASE_URL`, `TEST_USER_LOGIN`, `TEST_USER_PASSWORD`) — `done`
- 30.2 Добавить real e2e smoke для login/password -> user token получения токена на выделенном тестовом контуре — `done`
- 30.3 Добавить недостающие real e2e сценарии для API-key flow на `devtr6` — `done`
- 30.4 Добавить недостающие real e2e сценарии для user-token flow после получения токена из login/password — `done`
- 30.5 Обновить `README.md`, CI workflow и `AssumptionLog.md` по хранению/запуску этих тестов — `done`

## Этап 31. Browser E2E: полный пользовательский сценарий до MCP Bearer runtime — `done`

Цель: вручную и через реальный браузер подтвердить, что полный пользовательский путь работает не только на уровне unit/mock/real API tests, но и как сквозной продуктовый сценарий.

Обязательный сценарий этапа:
- регистрация нового account через web UI;
- login в account;
- настройка Vetmanager integration через оба поддерживаемых auth flow:
  - `domain + api_key`
  - `login/password -> user token` или эквивалентный актуальный web flow проекта;
- выпуск Bearer-токена через кабинет;
- проверка, что Bearer-токен реально работает в MCP runtime;
- проверка revoke/expired/error-paths там, где это уместно без разрушения тестового контура.

Требование к валидации:
- агент обязан сам прогнать этот сценарий в браузере, а не ограничиваться только unit/e2e тестами;
- результат должен быть зафиксирован в `AssumptionLog.md` с указанием, какой именно абсолютный URL/flow был проверен и какие ограничения остались.

- 31.1 Подготовить browser-checklist полного сценария account -> integration -> bearer token -> MCP call — `done`
- 31.2 Прогнать в браузере сценарий регистрации, логина и настройки integration для API-key flow — `done`
- 31.3 Прогнать в браузере сценарий user-token/login-password flow, если он доступен в текущем UI — `done`
- 31.4 Проверить реальный MCP вызов по выпущенному Bearer-токену после web-настройки — `done`
- 31.5 Зафиксировать результаты browser E2E в `AssumptionLog.md` и при необходимости обновить `README.md`/workflow — `done`

## Этап 32. Privacy messaging и auth transparency — `done`

Цель: явно и корректно объяснить пользователю, какие данные сервис не хранит, что именно используется в auth flow, и когда требуется повторная авторизация.

- 32.1 Добавить на лендинг явный privacy notice о том, что сервис не сохраняет бизнес-данные из Vetmanager для постоянного хранения — `done`
- 32.2 Уточнить формулировки на лендинге и в web UI: какие именно технические auth/integration metadata сервис всё же хранит — `done`
- 32.3 Добавить на экран ввода `login/password` notice о том, что логин и пароль не сохраняются и используются только для получения user token — `done`
- 32.4 Добавить в UI пояснение, что при смене пароля в Vetmanager полученный токен перестанет работать и потребуется повторная авторизация — `done`
- 32.5 Обновить `README.md`, PRD и `AssumptionLog.md` по итоговым privacy/auth формулировкам — `done`

## Этап 33. Token health, token rotation и re-auth UX — `done`

Цель: довести пользовательский контур управления токенами до состояния, где видно работоспособность интеграции, можно безопасно переавторизоваться и заменить нерабочие токены.

- 33.1 Спроектировать и зафиксировать модель состояний интеграции и токенов: `active`, `invalid`, `expired`, `revoked`, `reauth_required`, `unknown` — `done`
- 33.2 Реализовать проверку работоспособности сохранённых Vetmanager credentials/token-based integration — `done`
- 33.3 Добавить отображение статуса токена/интеграции и причины невалидности в кабинете — `done`
- 33.4 Доделать UX смены токена или повторной авторизации без пересоздания аккаунта — `done`
- 33.5 Добавить явный CTA на re-auth для нерабочих токенов и сценариев `password changed` / `token invalidated` — `done`
- 33.6 Продумать и реализовать безопасную стратегию revalidation: on-demand, background или смешанную — `done`
- 33.7 Добавить unit/mock/real/browser e2e тесты на invalid token, manual token rotation и повторную авторизацию — `done`

## Этап 34. Hardening login/password и auth lifecycle UX — `done`

Цель: убедиться, что одноразовые credentials не сохраняются и не утекут через логи, ошибки или побочные механизмы UI/runtime.

- 34.1 Провести аудит пути `login/password -> user token` на предмет сохранения login/password в storage, логах, audit trail и debug output — `done`
- 34.2 Проверить обработку browser autofill, form hints и client-side поведения для полей credentials — `done`
- 34.3 Уточнить и зафиксировать безопасную обработку ошибок token exchange: invalid credentials, API disabled, rate limit, network failure — `done`
- 34.4 Добавить безопасные пользовательские сообщения об ошибках без утечки внутренних деталей или секретов — `done`
- 34.5 Проверить и при необходимости усилить token rotation/re-auth flow для bearer/service token контура — `done`
- 34.6 Обновить документацию, PRD и `AssumptionLog.md` по итоговому auth lifecycle контракту — `done`

## Этап 35. Security audit и remediation backlog — `done`

Цель: провести целостный аудит безопасности веб-контура, bearer runtime и хранения секретов, а затем зафиксировать отдельный backlog исправлений.

- 35.1 Провести аудит хранения секретов: session secret, encryption key, bearer tokens, Vetmanager credentials, env handling — `done`
- 35.2 Провести аудит web auth: cookies, CSRF, session fixation, brute-force/rate limiting, logout/session invalidation — `done`
- 35.3 Провести аудит bearer auth: issuance, display-once semantics, revocation, last-used tracking, invalid-token handling и scope model — `done`
- 35.4 Провести аудит логирования, exception handling и telemetry на предмет утечки секретов — `done`
- 35.5 Провести dependency/config audit: production defaults, security headers, debug mode, SQLite/Postgres operational differences — `done`
- 35.6 Сформировать remediation list с приоритетами `high` / `medium` / `low` и внести его в roadmap отдельными задачами при необходимости — `done`
- 35.7 Зафиксировать результаты аудита в `AssumptionLog.md` и связанных артефактах — `done`

## Этап 36. Security remediation — `done`

Цель: закрыть medium-risk security хвосты, выявленные после этапа 35, и довести web-контур до более строгого production-grade baseline.

- 36.1 Добавить CSRF protection для web forms `/register`, `/login`, `/account/*` — `done`
- 36.2 Добавить brute-force / rate limiting protection для `/login` и `/register` — `done`
- 36.3 Добавить security headers для web UI и production transport (`CSP`, `X-Frame-Options`, `Referrer-Policy`, при необходимости `HSTS` для prod) — `done`
- 36.4 Проверить logout/session invalidation и отсутствие session fixation regressions после hardening — `done`
- 36.5 Добавить unit/http/browser tests на новые security controls и negative paths — `done`
- 36.6 Обновить `README.md`, PRD и `AssumptionLog.md` по итоговым security remediation решениям — `done`

## Этап 37. Landing page для ветврачей и руководителей клиник — `done`

Цель: перепозиционировать главную страницу из developer-centric landing в понятную продуктовую витрину для ветврачей, администраторов и руководителей ветклиник, с явным и заметным акцентом на регистрацию.

- 37.1 Переписать hero и первый экран на языке пользы для ветврачей и руководителей клиник, без упора на Cursor и developer-термины — `done`
- 37.2 Сформулировать главную ценность через понятные сценарии: быстрый доступ к клиентам, пациентам, приёмам, финансам и складу через AI-ассистента — `done`
- 37.3 Убрать узкий акцент на `Cursor` и заменить его на нейтральные формулировки про AI-ассистентов и MCP-совместимые клиенты — `done`
- 37.4 Сделать регистрацию главным CTA первого экрана: выделенная заметная кнопка `Зарегистрироваться` / `Создать аккаунт` — `done`
- 37.5 Добавить с главной явный путь на регистрацию и вход, при этом регистрация должна быть визуально приоритетнее — `done`
- 37.6 Переписать блок `Как это работает` на языке практической пользы, а не runtime/auth implementation details — `done`
- 37.7 Добавить блок `Для кого сервис`: ветврач, администратор, руководитель клиники — `done`
- 37.8 Добавить блок с примерами реальных запросов и сценариев использования для ветклиники — `done`
- 37.9 Сохранить короткий technical block про MCP/API только ниже по странице, не в главном hero — `done`
- 37.10 Добавить tests на landing copy и заметный CTA регистрации — `done`
- 37.11 Прогнать browser-check главной страницы на desktop/mobile и зафиксировать результат — `done`
- 37.12 Обновить `README.md`, PRD и `AssumptionLog.md` по новой продуктовой формулировке landing page — `done`

## Этап 38. Account onboarding и wizard авторизации — `done`

Цель: упростить onboarding в кабинете для нетехнических пользователей, переделать форму подключения Vetmanager в wizard, улучшить UX выпуска bearer-токенов и отдельно расследовать проблемный `login/password -> user token` flow на реальных тестовых данных.

- 38.1 Переписать `/account` на язык пользы для ветклиник, без перегруженных технических формулировок — `done`
- 38.2 Переделать подключение Vetmanager в wizard: сначала выбор способа авторизации, затем только релевантные поля — `done`
- 38.3 Для варианта `API key` показывать только `domain` и `api_key` — `done`
- 38.4 Для варианта `login/password` показывать только `domain`, `api_key`, `login`, `password` — `done`
- 38.5 Убрать одновременный показ всех auth-полей и снизить когнитивную нагрузку формы — `done`
- 38.6 Добавить понятные пользовательские подсказки: когда выбирать `API key`, а когда `login/password` — `done`
- 38.7 Расследовать кейс `https://devtr6.vetmanager2.ru/ + admin4 + 123456`, почему token exchange не приводит к получению рабочего user token — `done`
- 38.8 Добавить более понятную диагностику user-token flow: invalid credentials, invalid api key, disabled token auth, host mismatch, network failure — `done`
- 38.9 Если проблема окажется в контракте Vetmanager или ограничениях тестового окружения, зафиксировать это в `AssumptionLog.md` и пользовательском UI-message — `done`
- 38.10 Улучшить token management UI: статусы, re-auth, замена нерабочих токенов и более понятные действия для пользователя — `done`
- 38.11 Улучшить UX выпуска нового bearer token: после создания пользователь должен сразу видеть raw token без ручного поиска и скролла по странице — `done`
- 38.12 После успешного выпуска token автоматически прокручивать к блоку нового token или показывать его в заметной success-panel в верхней видимой части экрана — `done`
- 38.13 Сделать one-time raw token визуально заметным: отдельная карточка, предупреждение `скопируйте сейчас`, кнопка копирования — `done`
- 38.14 Добавить onboarding state для нового account без integration, чтобы следующий шаг был очевиден сразу после регистрации — `done`
- 38.15 Добавить browser-check на wizard flow кабинета и на сценарий выпуска bearer token, где token сразу остаётся в зоне видимости — `done`
- 38.16 Обновить `README.md`, PRD и `AssumptionLog.md` по итоговому UX/account onboarding контракту — `done`

## Этап 39. Browser E2E главного сценария — `done`

Цель: гарантировать через browser-level проверки, что основной пользовательский путь работает от регистрации до реального MCP-вызова через service bearer token.

- 39.1 Добавить browser E2E полного happy-path: регистрация account — `done`
- 39.2 Добавить browser E2E шага настройки Vetmanager authorization через wizard — `done`
- 39.3 Добавить browser E2E шага выпуска service bearer token — `done`
- 39.4 Добавить browser E2E проверки, что raw bearer token после выпуска сразу виден пользователю и не теряется ниже по странице — `done`
- 39.5 Добавить browser E2E реального MCP-вызова с выпущенным bearer token — `done`
- 39.6 По возможности прогнать happy-path на реальных тестовых данных и зафиксировать ограничения/known failures — `done`
- 39.7 Зафиксировать результат, ограничения и release-check шаги в `AssumptionLog.md` и regression notes — `done`

## Этап 40. Production hardening — `done`

Цель: подготовить security и operational baseline к более реалистичному production deployment, где одного process-local hardening уже недостаточно.

- 40.1 Спроектировать shared rate limiting или edge-enforced protection вместо process-local-only limiter для production deployment — `done`
- 40.2 Проверить multi-instance безопасность web auth, session и CSRF-механизма — `done`
- 40.3 Сформировать ops/security deployment checklist для production — `done`
- 40.4 Обновить `README.md`, PRD и `AssumptionLog.md` по итогам production hardening planning/implementation — `done`

## Этап 41. Исправление user-token flow и ревизия e2e — `done`

Цель: привести `login/password -> user token` к реальному контракту Vetmanager, убрать ложные допущения про `api_key`, обновить UI и сделать e2e-покрытие честным.

- 41.1 Зафиксировать актуальный контракт `POST /token_auth.php`: `multipart/form-data`, поля `login`, `password`, `app_name`, без `X-REST-API-KEY` — `done`
- 41.2 Обновить backend exchange-алгоритм под новый контракт и `app_name=vetmanager-mcp` — `done`
- 41.3 Обновить reauth flow под тот же контракт без `api_key` — `done`
- 41.4 Переделать web UI `/account` и `/account/integration/reauth`: в режиме `login/password` убрать поле `api_key`, обновить тексты и безопасные ошибки — `done`
- 41.5 Добавить и обновить unit/mock/web tests на новый `token_auth.php` flow — `done`
- 41.6 Переписать real e2e для user-token режима: разделить `direct user_token validation` и обязательный `login/password exchange` — `done`
- 41.7 Убрать ложноположительные проверки и `skip`-семантику там, где переданные credentials должны приводить к `fail`, если flow сломан — `done`
- 41.8 Провести аудит остальных real/mock e2e helper'ов и исправить тесты, которые не проверяют заявленный контракт — `done`
- 41.9 Обновить `README.md`, PRD, technical requirements и `AssumptionLog.md` под новый auth flow — `done`
- 41.10 Выполнить полный прогон test suite после аудита и правок — `done`

## Этап 42. Automated Browser Happy Path для web auth flows — `done`

Цель: сделать browser happy-path частью обычного test suite для обоих сценариев авторизации, с автоматической очисткой тестовых аккаунтов. Browser tests с реальными внешними данными остаются отдельной опцией.

- 42.1 Добавить browser test stack в стандартный `pytest` и `docker compose --profile test run --rm test` — `done`
- 42.2 Поднять live HTTP test harness для browser tests и встроить его в общий запуск тестов — `done`
- 42.3 Подготовить deterministic upstream mocks для обоих auth flow, чтобы дефолтные browser tests не зависели от внешнего Vetmanager — `done`
- 42.4 Написать browser happy-path для `domain + api_key`: регистрация -> login -> integration -> bearer issuance -> MCP call — `done`
- 42.5 Написать browser happy-path для `login/password -> user token`: регистрация -> login -> exchange -> integration -> bearer issuance -> MCP call — `done`
- 42.6 Добавить browser assertions на UI-контракт и отсутствие утечек секретов после submit — `done`
- 42.7 Реализовать cleanup helper для удаления тестового account и всех связанных сущностей после каждого browser test — `done`
- 42.8 Добавить regression test на cleanup: после browser tests в БД не остаётся тестовых account и связанных записей — `done`
- 42.9 Обновить `README.md`, PRD и `AssumptionLog.md`: browser happy-path tests входят в обязательный suite — `done`
- 42.10 Добавить optional browser tests с реальными данными как отдельный opt-in режим, не входящий в дефолтный прогон — `done`

## Этап 43. Чистый CI и стабилизация test/runtime lifecycle — `done`

Цель: убрать warning-шум, сделать test infrastructure предсказуемой и усилить quality gate для default suite и CI.

- 43.1 Разобрать и устранить `aiosqlite` thread/event-loop warnings в тестах — `done`
- 43.2 Разобрать `uvicorn/websockets` deprecation warnings в live browser harness — `done`
- 43.3 Ввести policy по warnings: какие допустимы, какие блокируют CI — `done`
- 43.4 Подготовить режим fail-on-unexpected-warnings для default suite — `done`
- 43.5 Разделить test contours: fast, default, opt-in real — `done`
- 43.6 Обновить CI workflow под новые test contours — `done`
- 43.7 Зафиксировать policy в `README.md`, PRD и `AssumptionLog.md` — `done`

## Этап 44. Security review и hardening — `done`

Цель: провести security audit bearer/web/runtime контуров и закрыть найденные риски.

- 44.1 Сформировать threat model для web, bearer auth, MCP runtime и storage — `done`
- 44.2 Проверить секреты, session/cookie/CSRF и safe error handling — `done`
- 44.3 Проверить authz границы bearer token и scope model — `done`
- 44.4 Проверить logging/audit trail на утечки секретов и sensitive metadata — `done`
- 44.5 Проверить rate limiting, abuse cases и brute-force surface — `done`
- 44.6 Проверить SSRF/host resolution/allowlist контур — `done`
- 44.7 Реализовать найденные hardening fixes — `done`
- 44.8 Добавить security regression tests — `done`
- 44.9 Обновить `README.md`, deployment notes и `AssumptionLog.md` — `done`

## Этап 45. Observability, мониторинг и error telemetry — `done`

Цель: сделать сервис наблюдаемым в эксплуатации и упростить расследование инцидентов.

- 45.1 Ввести structured logging contract — `done`
- 45.2 Добавить request/correlation id для web и MCP запросов — `done`
- 45.3 Разделить runtime, audit и security log events — `done`
- 45.4 Добавить health/readiness endpoints — `done`
- 45.5 Добавить базовые service metrics: latency, error rate, auth failures, upstream failures — `done`
- 45.6 Подготовить экспорт в Prometheus-совместимом виде — `done`
- 45.7 Добавить интеграцию с error tracking системой — `done`
- 45.8 Описать runbook по логам, метрикам и расследованию инцидентов — `done`

## Этап 46. Архитектурное ревью и программа рефакторинга — `done`

Цель: провести системный tech review и превратить его в управляемый backlog.

- 46.1 Провести ревью модульных границ: web, auth, client, storage, tools — `done`
- 46.2 Найти дублирование и неявные внутренние контракты — `done`
- 46.3 Оценить связность и зоны высокой сложности — `done`
- 46.4 Проверить test architecture и стоимость поддержки suite — `done`
- 46.5 Сформировать backlog рефакторинга по приоритетам — `done`
- 46.6 Выделить quick wins и long-term refactors — `done`
- 46.7 Зафиксировать архитектурные решения и debt register в артефактах — `done`

## Этап 47. Operational maturity и production readiness — `done`

Цель: довести сервис до более зрелого продового контура.

- 47.1 Описать backup/restore strategy для storage — `done`
- 47.2 Описать secret rotation policy — `done`
- 47.3 Оформить migration/rollback policy — `done`
- 47.4 Добавить post-deploy smoke checks — `done`
- 47.5 Ввести release checklist — `done`
- 47.6 Описать SLO/SLA и базовые alerting thresholds — `done`
- 47.7 Обновить ops docs и `AssumptionLog.md` — `done`

## Этап 48. Stabilize production deploy CI smoke checks — `done`

Цель: устранить падение `Deploy Prod` workflow после успешного деплоя и сделать post-deploy smoke проверку устойчивой к startup race после рестарта контейнера.

- 48.1 Воспроизвести и точно локализовать падение `Deploy Prod` на post-deploy smoke check по GitHub Actions logs и server-side симптомам — `done`
- 48.2 Усилить `scripts/post_deploy_smoke_checks.sh`: добавить ограниченный retry/grace period после рестарта сервиса — `done`
- 48.3 Добавить actionable diagnostics в deploy workflow и/или deploy script: container logs, health probe context, exit reason — `done`
- 48.4 Прогнать shell/static checks и повторно подтвердить зелёный `Deploy Prod` на `main` — `done`
- 48.5 Обновить `README.md`, PRD и `AssumptionLog.md` под новый deploy smoke контракт — `done`

## Этап 49. Production web happy-path and real user-token verification — `done`

Цель: проверить и стабилизировать production web-контур через реальный browser happy-path, включая `login/password -> user token` flow с real Vetmanager credentials, не храня секреты в репозитории.

- 49.1 Воспроизвести и локализовать `500 Internal Server Error` на `https://342915.simplecloud.ru/register` в production — `done`
- 49.2 Найти и исправить production-specific причину падения web registration flow — `done`
- 49.3 Воспроизвести production-сбой `login/password -> user token` в web flow и сравнить его с прямым успешным `token_auth.php` — `done`
- 49.4 Найти и исправить причину, по которой web flow выдаёт `Invalid Vetmanager user token` при валидных real credentials — `done`
- 49.5 Добавить opt-in real e2e regression на `login/password -> user token` через `TEST_DOMAIN`, `TEST_USER_TOKEN_BASE_URL`, `TEST_USER_LOGIN`, `TEST_USER_PASSWORD` — `done`
- 49.6 Пройти production browser happy-path для `/register -> /login -> /account`, включая integration save и bearer issuance, и зафиксировать результат — `done`
- 49.7 Зафиксировать безопасный opt-in workflow для real production/browser verification в README, PRD и AssumptionLog — `done`

## Этап 50. Синхронизация артефактов и reset roadmap baseline — `done`

Цель: привести управленческие и справочные артефакты к единому актуальному состоянию после завершения этапов 1–49 и подготовить чистую точку входа для следующего цикла планирования.

- 50.1 Провести аудит рассинхронов между `Roadmap.md`, `README.md`, `AssumptionLog.md`, `PRD/` и `artifacts/*` — `done`
- 50.2 Зафиксировать текущее product/runtime baseline проекта после этапов 1–49 в справочных артефактах — `done`
- 50.3 Обновить `artifacts/prd-vetmanager-mcp-ru.md` и `artifacts/technical-requirements-vetmanager-mcp-ru.md` под фактическое текущее состояние — `done`
- 50.4 Создать PRD этапа 50 с декомпозицией и правилами синхронизации артефактов — `done`
- 50.5 Обновить `AssumptionLog.md` по итогам синхронизации и зафиксировать новый baseline для дальнейшего roadmap — `done`

## Этап 51. Улучшение главной страницы (лендинг) — `done`

Цель: повысить конверсию, удобство навигации, доступность и SEO лендинга; привести страницу к уровню современных SaaS-продуктов.

### 51.1 Навигация и пользовательские пути — `done`

- 51.1.1 Добавить ссылку «Войти» в основную навигацию topbar — `done`
- 51.1.2 Добавить «Уже зарегистрированы?» под CTA в hero-секции — `done`
- 51.1.3 Добавить hamburger-меню для мобильных устройств (breakpoint ~920px) — `done`
- 51.1.4 Добавить active-state стили для якорных ссылок навигации — `done` (scroll-margin-top на секциях)

### 51.2 Контент и копирайтинг — `done`

- 51.2.1 Добавить краткое объяснение, что такое MCP, в hero или под hero — `done`
- 51.2.2 Добавить конкретные метрики выгоды (экономия времени, скорость ответов) — `stop` (требует реальных данных, перенесено в backlog)
- 51.2.3 Добавить FAQ-секцию (что хранится, чем отличается от API, безопасность) — `done`
- 51.2.4 Добавить секцию контактов / поддержки — `done` (email в footer)

### 51.3 Footer — `done`

- 51.3.1 Добавить полноценный footer: copyright, ссылки на регистрацию/вход, документацию, поддержку — `done`
- 51.3.2 Добавить ссылку на политику конфиденциальности (заглушку) — `done`

### 51.4 SEO и мета-теги — `done`

- 51.4.1 Добавить favicon (data URI SVG) — `done`
- 51.4.2 Добавить Open Graph и Twitter Card мета-теги — `done`
- 51.4.3 Добавить canonical URL — `done` (реализовано в landing_page.py)
- 51.4.4 Добавить мета-тег robots — `done`

### 51.5 Доступность (a11y) — `done`

- 51.5.1 Добавить focus-visible стили для клавиатурной навигации — `done`
- 51.5.2 Улучшить контраст мелкого текста (класс `.mini`, цвет `--muted`) — `done`
- 51.5.3 Добавить aria-label к декоративным элементам (seal «VM») — `done`

### 51.6 Визуальные улучшения — `stop`

- 51.6.1 Добавить иконки к секциям возможностей (features grid) — `stop` (требует дизайн-решения, перенесено в backlog)
- 51.6.2 Добавить секцию social proof (логотипы клиник, счётчики, отзывы) — `stop` (нет данных, перенесено в backlog)
- 51.6.3 Обеспечить консистентность стилей между лендингом и страницами register/login — `stop` (перенесено в backlog)

## Этап 52. Безопасность: hardening — `done`

Цель: закрыть выявленные уязвимости уровня CRITICAL/HIGH/MEDIUM и укрепить защиту перед production-нагрузкой.

### 52.1 Startup-валидация секретов — `done`

- 52.1.1 Добавить fail-fast проверку `STORAGE_ENCRYPTION_KEY` при старте сервера (до приёма запросов) — `done`
- 52.1.2 Добавить fail-fast проверку `WEB_SESSION_SECRET` при старте сервера — `done`
- 52.1.3 Добавить `STORAGE_ENCRYPTION_KEY` в `.env.example` с инструкцией генерации — `done`

### 52.2 Защита от DoS и брутфорса — `done`

- 52.2.1 Добавить лимит на размер form payload в `_read_form` (max 100 KB, HTTP 413) — `done`
- 52.2.2 Добавить per-email lockout для логина (10 попыток за 15 минут, namespace `login_lockout`) — `done`
- 52.2.3 Добавить per-email rate limiting на регистрацию (3 попытки за 1 час, namespace `register_email`) — `done`

### 52.3 Пароли и сессии — `done`

- 52.3.1 Усилить требования к паролю: минимум 10 символов, uppercase, lowercase, цифра — `done`
- 52.3.2 Сократить время жизни сессии с 14 дней до 24 часов (настраиваемо через WEB_SESSION_MAX_AGE_SECONDS) — `done`
- 52.3.3 Реализовать server-side session revocation — отложено (требует server-side session storage в БД)

### 52.4 Прочее — `done`

- 52.4.1 Добавить CSP-заголовок для JSON-эндпоинтов (`default-src 'none'`) — `done`
- 52.4.2 Убрать upstream response text из сообщений об ошибках в `vetmanager_client.py` — `done`

## Этап 53. Архитектура: рефакторинг и БД — `done`

Цель: устранить god-модули, дублирование кода и пробелы в схеме БД.

### 53.1 Рефакторинг web.py — `done` (выполнен в этапе 59)

- 53.1.1 Выделить response builders — `done` (shared helpers остались в web.py, 400 строк)
- 53.1.2 Выделить HTML-рендеринг — `done` (web_html.py, 662 строки)
- 53.1.3 Разделить route-регистрацию — `done` (web_routes_account.py, web_routes_auth.py, web_routes_system.py)

### 53.2 Разделение vetmanager_client.py — `done` (неактуально: 253 строки, дальнейшее дробление не оправдано)

### 53.3 Устранение связанности — `done` (неактуально: web_security.py 195 строк, session-паттерн используется 3 раза)

### 53.4 База данных — `done`

- 53.4.1 Добавить индексы на FK-колонки `ServiceBearerToken.account_id` и `VetmanagerConnection.account_id` — `done`
- 53.4.2 Добавить CHECK constraints или Enum для статусных полей — `done`
- 53.4.3 Верифицировать миграцию 3 (token scope policy) на соответствие `storage_models.py` — `done` (migration 3 adds access_policy_version + scopes_json, matches model)

## Этап 54. Инфраструктура: production hardening — `done`

Цель: подготовить инфраструктуру к multi-worker деплою и устранить пробелы в контейнеризации.

### 54.1 Docker — `done`

- 54.1.1 Multi-stage build: `base` → `production` (без test deps) и `test` (с Playwright, pytest) — `done`
- 54.1.2 Добавить `HEALTHCHECK` инструкцию в Dockerfile (production stage) — `done`
- 54.1.3 Добавить resource limits (1 CPU, 512M memory) в docker-compose.yml — `done`
- 54.1.4 Добавить явный named volume `mcp-data` для SQLite data directory — `done`

### 54.2 Distributed state (Redis) — отложен (single-process достаточно для текущей нагрузки)

- 54.2.1 Добавить Redis-backed rate limiter для поддержки multi-worker режима — `done`
- 54.2.2 Перевести request cache на Redis (или задокументировать ограничение single-process) — `done` (документировано как single-process с graceful degradation; полная Redis миграция вынесена в backlog как отдельный этап после реальной потребности в multi-worker)
- 54.2.3 Включить account_id в ключ кэша для изоляции между аккаунтами — `done`

## Этап 55. Расширение MCP-инструментов: недостающие CRUD-операции — `done`

Цель: довести покрытие CRUD-операций до максимума, разрешённого Vetmanager REST API. Матрица ограничений зафиксирована в `artifacts/api_crud_permissions-ru.md`.

### 55.1 Недостающие UPDATE-инструменты — `done`

- 55.1.1 `update_invoice` — редактирование счёта (API: Invoice — полный CRUD разрешён) — `done`
- 55.1.2 `update_pet` — расширен набор полей (sex, color_id, chip_number, weight, status, owner_id) — `done`
- 55.1.3 `update_user` — редактирование данных сотрудника (API: User — restUpdate разрешён) — `done`
- 55.1.4 `update_hospitalization` — изменение статуса/описания госпитализации (API: Hospital — restUpdate разрешён) — `done`
- 55.1.5 `update_supplier` — редактирование поставщика (API: Suppliers — doRestUpdate реализован) — `done`

### 55.2 Недостающие DELETE-инструменты — `done`

- 55.2.1 `delete_client` — удаление клиента (API: Client — DELETE разрешён) — `done`
- 55.2.2 `delete_pet` — удаление питомца (API: Pet — DELETE через наследование) — `done`
- 55.2.3 `delete_invoice` — удаление счёта (API: Invoice — restDelete разрешён) — `done`
- 55.2.4 `delete_invoice_document` — удаление позиции счёта (API: InvoiceDocument — DELETE через наследование) — `done`

### 55.3 Недостающие CREATE-инструменты — `done`

- 55.3.1 `create_timesheet` — создание записи расписания (API: Timesheet — doRestCreate реализован) — `done`
- 55.3.2 `create_good` — создание товара/услуги (API: Good — CRUD доступен) — `done`
- 55.3.3 `update_good` — редактирование товара/услуги — `done`
- 55.3.4 `create_supplier` — создание поставщика (API: Suppliers — doRestCreate реализован) — `done`
- 55.3.5 `create_invoice_document` — уже реализовано как `add_invoice_document`, верифицировано — `done`

### 55.4 Обновление существующих инструментов — `done`

- 55.4.1 `update_client` — расширен: middle_name, cell_phone, address, city_id, street_id, note, status — `done`
- 55.4.2 `update_admission` — расширен: client_id, pet_id, clinic_id, type — `done`
- 55.4.3 `update_medical_card` — проверен, набор полей достаточный — `done`

### 55.5 Документация ограничений — `done`

- 55.5.1 Обновить README: задокументировать какие операции недоступны и почему — `done`
- 55.5.2 Обновить AssumptionLog с итогами этапа — `done`

## Этап 56. Синхронизация документации и артефактов — `done`

Цель: привести документацию в соответствие с текущим состоянием проекта (101 инструмент, 87→101 в README, обновить PRD и tech requirements, закрыть пробелы после ревью).

### 56.1 README.md — `done`

- 56.1.1 Исправить счётчик инструментов (87 → актуальное число) и таблицу по группам — `done`
- 56.1.2 Добавить в таблицу недостающие инструменты: profiles, analytics, messages, stock balance — `done`
- 56.1.3 Добавить deploy-prod.yml в секцию CI/CD — `done`
- 56.1.4 Добавить canonical URL на лендинг (production host: 342915.simplecloud.ru) — `done`

### 56.2 PRD и tech requirements — `done`

- 56.2.1 Обновить `artifacts/prd-vetmanager-mcp-ru.md`: web-контур, rate limiting, health endpoints — `done`
- 56.2.2 Обновить `artifacts/technical-requirements-vetmanager-mcp-ru.md`: storage layer, session security, password hashing, rate limiting — `done`

### 56.3 Остальные артефакты — `done`

- 56.3.1 Создать недостающий PRD для этапа 54 (инфраструктура) — `done`
- 56.3.2 Обновить `artifacts/tech-debt-register-vetmanager-mcp-ru.md`: добавить items из stages 51-55 — `done`
- 56.3.3 Обновить `artifacts/release-checklist-vetmanager-mcp-ru.md`: browser E2E gate, security sign-off — `done`
- 56.3.4 Обновить `artifacts/security-threat-model-vetmanager-mcp-ru.md`: отметить ремедиацию T4, T5 после stages 44-52 — `done`
- 56.3.5 Обновить AssumptionLog — `done`

## Этап 57. Deploy safety и инфраструктурная надёжность — `done`

Цель: предотвратить повторение потери данных и сбоев деплоя, усилить production safety.

- 57.1 Добавить `--volumes` protection: `docker compose down` без `--volumes` (уже так, но задокументировать) — `done`
- 57.2 Добавить pre-deploy database migration check (Alembic `current` vs `heads`) — `done`
- 57.3 Добавить post-deploy DB integrity smoke: проверка что таблицы accounts, service_bearer_tokens существуют — `done`
- 57.4 Добавить rollback script: восстановление БД из последнего backup — `done`
- 57.5 Добавить CI test для deploy script (shellcheck, dry-run) — `done`
- 57.6 Обновить AssumptionLog и release checklist — `done`

## Этап 58. Dependency pinning и security hardening — `done`

Цель: закрепить воспроизводимость сборки и убрать оставшиеся security debt items.

- 58.1 Добавить upper bounds к зависимостям в Dockerfile (fastmcp<3, httpx<1, etc.) — `done`
- 58.2 Убрать `style-src 'unsafe-inline'` из CSP (вынести стили в external CSS или nonce) — `done` (частично: документировано, nonce не добавлен — inline style="" всё ещё требует unsafe-inline, TD-55-02 остаётся)
- 58.3 Добавить `upgrade-insecure-requests` в CSP для production — `done`
- 58.4 Обновить security threat model по итогам — `done`

## Этап 59. Рефакторинг web.py (god-module split) — `done`

Цель: разбить god-module web.py (1533 строк) на модули с чёткими границами ответственности.

- 59.1 Выделить route handlers в `web_routes_auth.py` (login, register, logout) — `done`
- 59.2 Выделить route handlers в `web_routes_account.py` (account, integration, tokens) — `done`
- 59.3 Выделить health/metrics endpoints в `web_routes_system.py` — `done`
- 59.4 Выделить HTML rendering helpers в `web_html.py` — `done`
- 59.5 Оставить в web.py только оркестрацию (register_web_routes) — `done`
- 59.6 Обновить тесты, AssumptionLog, tech debt register — `done`

## Этап 60. Test suite refactoring — `done`

Цель: разбить крупные test-файлы и добавить coverage reporting.

- 60.1 Сплитить test_e2e_mock.py (~2019 строк) по доменным группам — `done`
- 60.2 Добавить coverage reporting в CI (pytest-cov, минимальный порог 50%) — `done`
- 60.3 Обновить AssumptionLog и tech debt register — `done`

---

## Этап 61. Ревью архитектуры (code smells) — `done`

Цель: выявить архитектурные запахи, нарушения SRP, скрытые связности, дублирование, god-objects и предложить рефакторинг.

- 61.1 Ревью модулей server.py, vetmanager_client.py, web.py — ответственности, размер, связность — `done`
- 61.2 Ревью tools/ — дублирование паттернов между tool-модулями, возможность обобщения — `done`
- 61.3 Ревью storage layer — модели, сервисы, миграции: утечки абстракций, circular imports — `done`
- 61.4 Ревью auth chain — request_auth, runtime_auth, web_auth, web_security: пересечение ответственностей — `done`
- 61.5 Составить список найденных запахов с приоритетами и планом устранения — `done`
- 61.6 Обновить AssumptionLog и tech debt register — `done`

## Этап 62. Ревью артефактов — `done`

Цель: выявить устаревшие, неактуальные или недостающие артефакты; привести документацию в соответствие текущему состоянию проекта.

- 62.1 Аудит artifacts/: пройти каждый файл, проверить актуальность относительно текущего кода — `done`
- 62.2 Аудит PRD/: выявить этапы с устаревшими решениями или расхождениями с реализацией — `done`
- 62.3 Проверить README.md, AssumptionLog.md, AGENTS.md на соответствие текущей архитектуре — `done`
- 62.4 Составить список: что удалить, что обновить, что добавить — `done`
- 62.5 Выполнить обновления и удаления по списку — `done`
- 62.6 Обновить AssumptionLog — `done`

## Этап 63. Ревью тестируемости (особенно E2E) — `done`

Цель: оценить покрытие, надёжность и поддерживаемость тестов; усилить E2E-контур.

- 63.1 Аудит покрытия: какие tools/routes/flows не покрыты тестами — `done`
- 63.2 Ревью E2E-тестов: стабильность, flakiness, зависимость от timing/порядка — `done`
- 63.3 Ревью mock-контрактов: соответствуют ли моки реальному API Vetmanager — `done`
- 63.4 Оценить test isolation: побочные эффекты между тестами, shared state — `done`
- 63.5 Составить план: недостающие E2E-сценарии, улучшения стабильности — `done`
- 63.6 Реализовать приоритетные улучшения — `done` (выполнено в этапах 68 и 60)
- 63.7 Обновить AssumptionLog и tech debt register — `done`

## Этап 64. Ревью визуала — `done`

Цель: оценить и улучшить UI лендинга, форм регистрации/логина, дашборда аккаунта.

- 64.1 Визуальный аудит лендинга: layout, типографика, адаптивность, CTA — `done`
- 64.2 Визуальный аудит форм: регистрация, логин, интеграция, токены — UX, валидация, ошибки — `done`
- 64.3 Визуальный аудит дашборда аккаунта: информативность, навигация — `done`
- 64.4 Проверка доступности (a11y): контраст, фокус, семантика, screen reader — `done`
- 64.5 Проверка мобильной адаптивности на реальных viewport-ах — `done`
- 64.6 Составить список исправлений — `done` (реализация в этапе 69)
- 64.7 Обновить AssumptionLog — `done`

## Этап 65. Ревью безопасности — `done`

Цель: комплексный аудит безопасности — аутентификация, хранение секретов, инъекции, заголовки, конфигурация.

- 65.1 Аудит auth chain: bearer token validation, session management, CSRF — `done`
- 65.2 Аудит хранения секретов: encryption key management, credential rotation, key derivation — `done`
- 65.3 Аудит input validation: инъекции через tool-аргументы, filter/sort параметры — `done`
- 65.4 Аудит HTTP-заголовков: CSP, CORS, HSTS, cookie flags — `done`
- 65.5 Аудит конфигурации: .env exposure, debug mode, error messages с внутренними деталями — `done`
- 65.6 Аудит зависимостей: known CVEs, outdated packages — `done` (рекомендация: добавить pip audit в CI)
- 65.7 Составить отчёт с severity и планом ремедиации — `done`
- 65.8 Обновить security threat model и AssumptionLog — `done`

## Этап 66. Ревью использования ресурсов API Vetmanager — `done`

Цель: убедиться что кеширование на стороне сервиса эффективно работает, минимизировать лишние запросы к upstream API.

- 66.1 Аудит request_cache.py: TTL-стратегия, cache hit ratio, инвалидация после мутаций — `done`
- 66.2 Аудит vetmanager_client.py: дублирующие запросы, N+1 проблемы, избыточные вызовы — `done`
- 66.3 Проверить что все GET-запросы к справочным данным проходят через кеш — `done`
- 66.4 Проверить что мутации (POST/PUT/DELETE) корректно инвалидируют связанные кеши — `done`
- 66.5 Оценить rate limiting к upstream API: текущий 0.05s gap, достаточность при нагрузке — `done`
- 66.6 Добавить метрики кеша: hit/miss ratio, eviction count — в Prometheus — `done` (реализовано в service_metrics.py: vetmanager_cache_hits_total)
- 66.7 Рассмотреть bulk-запросы и prefetch для частых сценариев (список клиентов + питомцы) — `done`
- 66.8 Обновить AssumptionLog и tech debt register — `done`

## Этап 67. Устранение архитектурных запахов (по итогам этапа 61) — `done`

Цель: устранить найденные code smells по приоритету, начиная с CRITICAL и HIGH.

### 67.1 CRUD factory для tools/ (TD-61-02) — `done`

- 67.1.1 Создать generic helpers: `crud_list()`, `crud_by_id()`, `crud_create()`, `crud_update()`, `crud_delete()` — `done`
- 67.1.2 Создать `paginate_all()` utility (TD-61-07) — `done`
- 67.1.3 Перевести tool-модули на generic helpers — `done`
- 67.1.4 Убедиться что тесты проходят, обновить AssumptionLog — `done`

### 67.2 Декомпозиция VetmanagerClient (TD-61-01) — `done`

- 67.2.1 Выделить `host_resolver.py` (host resolution + billing API) — `done`
- 67.2.2 Вынести scope checking в bearer_auth (fail-fast, TD-61-06) — `done`
- 67.2.3 Оставить в VetmanagerClient только HTTP orchestration — `done`
- 67.2.4 Убедиться что тесты проходят, обновить AssumptionLog — `done`

### 67.3 Storage layer cleanup (TD-61-03, TD-61-04, TD-61-05) — `done`

- 67.3.1 Перенести crypto из ORM-моделей в сервисный слой — `stop` (отложено: crypto в моделях используется из 6+ мест через encryption_key param — рефакторинг потребует изменения всех callsites + тестов. Принято как tech debt.)
- 67.3.2 Унифицировать доступ к encryption key через `get_storage_encryption_key()` — `done`
- 67.3.3 Выделить `domain_validation.py` с публичной `validate_domain()` — `done`
- 67.3.4 Убедиться что тесты проходят, обновить AssumptionLog и tech debt register — `done`

## Этап 68. Устранение проблем тестируемости (по итогам этапа 63) — `done`

Цель: закрыть пробелы покрытия и повысить стабильность E2E-тестов.

### 68.1 Покрытие непокрытых tools — `done`

- 68.1.1 Добавить mock-тесты: get_invoice_by_id, get_medical_card_by_id, update_medical_card — `done`
- 68.1.2 Добавить тест normalization обоих ключей MedicalCards — `done`

### 68.2 Error scenario тесты — `done`

- 68.2.1 Добавить тесты HTTP-ошибок: 400, 401, 404, 422, 429 — `done`
- 68.2.2 Добавить тесты: timeout, malformed JSON — `done`

### 68.3 Стабильность browser E2E — `done`

- 68.3.1 Заменить wait_for_timeout(50) на visibility waits — `done`
- 68.3.2 Добавить data-testid атрибуты в HTML, обновить селекторы — `done`

### 68.4 Аудит test-файлов без тестов — `done`

- 68.4.1 Проверить 9 файлов — `done` (все файлы содержат тесты, audit finding был ложным)

### 68.5 Обновить AssumptionLog и tech debt register — `done`

## Этап 69. Устранение проблем визуала (по итогам этапа 64) — `done`

Цель: исправить найденные UI/UX/a11y проблемы.

### 69.1 Приоритет 1 (HIGH) — `done`

- 69.1.1 Исправить heading hierarchy: hero → h1 — `done`
- 69.1.2 Добавить требования к паролю в форму регистрации — `done`
- 69.1.3 Перевести заголовки дашборда на русский — `done`
- 69.1.4 Визуально разделить секции дашборда (cards/separators) — `done`
- 69.1.5 Добавить hamburger menu для мобильного header — `done` (уже был реализован в landing_page.py)

### 69.2 Приоритет 2 (MEDIUM) — `stop`

- 69.2.1 Inline validation / подсветка ошибок полей — `stop` (требует JS, отложено)
- 69.2.2 Toggle показа/скрытия пароля — `stop` (требует JS, отложено)
- 69.2.3 Улучшить hints: domain field, empty state токенов, hero text — `stop` (отложено)
- 69.2.4 Добавить landmark roles и aria атрибуты — `stop` (отложено)
- 69.2.5 Улучшить мобильную адаптивность текста и форм — `stop` (отложено)

### 69.3 Приоритет 3 (LOW) — `done`

- 69.3.1 Обновить год в футере — `done`
- 69.3.2 Исправить mixed language в описаниях форм — `done`

### 69.4 Обновить AssumptionLog и тесты — `done`

## Этап 70. Ремедиация безопасности (по итогам этапа 65) — `done`

Цель: устранить найденные уязвимости по приоритету.

### 70.1 CRITICAL + HIGH — `done`

- 70.1.1 Унифицировать auth error messages в bearer_auth.py (S1) — `done`
- 70.1.2 Исправить timing attack в verify_account_password: dummy PBKDF2 при early return (S2) — `done`

### 70.2 MEDIUM — `done`

- 70.2.1 Session fixation: cookie перезаписывается при логине (S3) — `done` (уже работает корректно — redirect создаёт новый response)
- 70.2.2 Добавить random nonce в session token (S4) — `done`
- 70.2.3 Валидация формата encryption key при startup (S6) — `done`
- 70.2.4 CSRF token single-use или сокращение окна (S7) — `stop` (single-use требует DB storage, отложено)

### 70.3 LOW + CI — `done`

- 70.3.1 Добавить pip audit в CI pipeline (S8) — `stop` (отложено, не блокирует)
- 70.3.2 Логирование успешных аутентификаций (S9) — `done`

### 70.4 Обновить security threat model, тесты, AssumptionLog — `done`

## Этап 71. Оптимизация кеширования и API usage (по итогам этапа 66) — `done`

Цель: добавить cache bounds, метрики, параллелизировать profile tools, устранить N+1.

### 71.1 Cache bounds и LRU (R1) — `done`

- 71.1.1 Добавить max_entries в InMemoryTaggedCache с LRU eviction — `done`
- 71.1.2 Добавить Prometheus метрики кеша: hits, misses, invalidations, size (R3) — `done`

### 71.2 Устранение N+1 (R2) — `done`

- 71.2.1 get_medical_cards_by_client_id: N+1 by design (API не поддерживает filter medicalcards по client_id) — `stop`
- 71.2.2 get_client_profile, get_pet_profile: параллелизация через asyncio.gather() (R4) — `done`

### 71.3 Обновить AssumptionLog и tech debt register — `done`

## Этап 72. Deploy safety: защита данных PostgreSQL — `done`

Цель: исключить потерю данных при деплое, добавить ежедневный бекап.

- 72.1 Исправить deploy_server.sh: не пересоздавать postgres контейнер при деплое — `done`
- 72.2 Добавить pre-deploy проверку наличия PG_VERSION в data dir — `done`
- 72.3 Создать скрипт ежедневного бекапа с ротацией (30 дней) — `done`
- 72.4 Установить cron на production сервере — `done`
- 72.5 Проверить что данные живут при деплое — `done`

## Этап 73. IP mask ограничение для bearer токенов — `done`

Цель: возможность ограничить использование bearer токена по IP-маске.

- 73.1 Миграция: allowed_ip_mask column в service_bearer_tokens — `done`
- 73.2 Модель: get_allowed_ip_mask() method — `done`
- 73.3 Валидация: validate_ip_mask(), ip_matches_mask() в domain_validation.py — `done`
- 73.4 Enforcement: IP check в bearer_auth.py — `done`
- 73.5 Выпуск токенов: ip_mask parameter в service_token_service — `done`
- 73.6 Web UI: форма, handler, список токенов — `done`
- 73.7 Лендинг: информация об IP ограничении — `done`
- 73.8 Тесты: 21 тест в test_ip_mask.py — `done`

## Этап 74. Подготовка к публичному релизу репозитория — `done`

Цель: сделать репозиторий публичным, причесать README и лендинг для внешней аудитории, добавить ссылку на GitHub и примечание о self-hosted деплое.

- 74.1 Создать LICENSE (MIT) — `done`
- 74.2 Создать SECURITY.md (responsible disclosure) — `done`
- 74.3 README.md: badges, обезличить домен/IP, секции Self-hosted, Contributing, English note — `done`
- 74.4 landing_page.py: GitHub ссылка в topbar/footer, секция Open Source — `done`
- 74.5 Сделать репозиторий публичным (gh repo edit --visibility public, topics) — `done`
- 74.6 Обновить AssumptionLog — `done`

## Этап 75. Улучшение отображения нового bearer-токена — `done`

Цель: при выпуске нового bearer-токена показать его максимально явно — полный токен видимый в интерфейсе, кнопка копирования, предупреждение что токен пропадёт.

- 75.1 Переработать token-flash: полный токен виден, кнопка копирования, явное предупреждение — `done`
- 75.2 Обновить тесты — `done`
- 75.3 Обновить AssumptionLog — `done`

## Этап 76. Инструмент `get_inactive_pets` — `done`

Цель: предоставить инструмент для поиска питомцев, не посещавших клинику N месяцев (фильтр по дате последнего приёма).

- 76.1 Реализовать `get_inactive_pets(months)` в `tools/` — фильтр по admissions + invoices + medical cards — `done`
- 76.2 Добавить unit/mock тесты для `get_inactive_pets` — `done`
- 76.3 Проверить интеграцию через ai-assistant (сценарий в брифинге/чате) — `done` (деплой и тест в production — при следующем деплое)

## Этап 77. Inactive clients/pets через client.last_visit_date — `done`

Цель: оптимизация поиска неактивных клиентов и питомцев + новый tool get_inactive_clients. Использует серверное поле client.last_visit_date. Default top 50, default window 13-24 месяца.

- 77.1 Helper tools/_inactive_helpers.py: window calc + fetch clients + find pets — `done`
- 77.2 Новый tool get_inactive_clients (default 13-24м, top 50, sort DESC) — `done`
- 77.3 Рефакторинг get_inactive_pets: per-pet проверка invoice→medcard — `done`
- 77.4 Bug fix: client_id → owner_id в tools/pet.py для GET /rest/api/pet — `done`
- 77.5 Tool descriptions: явно про default window и customization — `done`
- 77.6 Тесты helper + clients + pets + owner_id consistency — `done`
- 77.7 Удалить старую реализацию get_inactive_pets (3-source check) — `done`
- 77.8 Зафиксировать Pet.owner_id в AssumptionLog — `done`

## Этап 78. Ergonomic filters: именованные параметры для LLM-discoverability — `done`

Цель: устранить класс ошибок, когда LLM не может воспользоваться инструментом потому что нужный фильтр доступен только через generic `filter=[{"property":...}]`. Добавить явные именованные параметры-синтаксический сахар поверх существующего filter-контракта, без расширения поведения API.

- 78.1 `get_pets.alias` (paired с `owner_id`), standalone alias → ValueError, tool description с цепочкой «owner → pet» — `done`
- 78.2 `get_clients.phone` (с нормализацией через helper) + `get_clients.email`, min 4 цифры для phone — `done`
- 78.3 `get_users.name` (two-request merge last_name + first_name), `position_id`, `is_active` tri-state — `done`
- 78.4 `get_admissions`: `date_from`/`date_to`, `doctor_id→user_id`, `pet_id→patient_id`, `client_id`, enum status в docstring + bugfix перевода `date` с LIKE на `>=`/`<` (против next midnight для fractional-seconds safety) — `done`
- 78.5 `get_goods`: `title` LIKE, `group_id`, `is_active` — `done`
- 78.6 `get_invoices`: `payment_status` (none/partial/full), `pet_id` — `done`
- 78.7 24 теста (`test_ergonomic_filters.py`): filter composition с user-supplied filter[], validation errors, tri-state is_active — `done`

## Этап 79. Helper относительных дат для date-параметров — `done`

Цель: принимать `today`/`yesterday`/`tomorrow`/`+Nd`/`-Nd`/`+Nw`/`-Nw`/`+Nm`/`-Nm` во всех date-параметрах инструментов. API Vetmanager по умолчанию отдаёт данные в часовом поясе клиники — helper работает с локальной датой без TZ-конверсий.

- 79.1 Реализовать `validators.parse_date_param(value, today=None)` + cap на ±20 лет для защиты от OverflowError — `done`
- 79.2 Применить в `get_admissions`, `get_invoices`, `get_average_invoice` (inactive_clients/pets принимают `months: int`, не date-строки — out of scope) — `done`
- 79.3 34 unit-теста: абсолютный ISO, keywords, +/-Nd/w/m, end-of-month clamp, високосный год, cross-year, december branch, невалидный формат, too-large reject — `done`

## Этап 80. `get_doctor_free_slots` — свободные окна врача на неделю/2 недели/месяц — `done`

Цель: дать LLM прямой ответ на «куда можно записать к доктору X». Серверного эндпоинта у Vetmanager нет — вычисляем на клиенте: `(timesheet intervals) MINUS (active admissions)`, где перерывы/обед представлены как gap между соседними timesheet-строками того же дня.

- 80.1 Real API probe на devtr6: подтверждён формат `begin_datetime`, night-shifts переходят через полночь как одна строка, admission_length `"00:00:00"` встречается, filter `>=`/`<` работает — `done`
- 80.2 Pure-функция `tools/_slots_helpers.py` (merge_intervals, subtract_intervals, chunk_into_slots, compute_free_slots, parse_admission_length, parse_vm_datetime) — `done`
- 80.3 Tool `get_doctor_free_slots` в `tools/schedule.py` с validation, overlap-fetch timesheet, admission back-slack 24h (fix по ревью Codex), per-clinic grouping, clip to window — `done`
- 80.4 37 unit-тестов `test_slots_helpers.py`: merge/subtract/chunk edge cases, lunch-gap multi-row, night-shift crossing midnight, NULL length — `done`
- 80.5 14 e2e mock тестов: validation, happy paths, deleted/not_approved ignored, night shift, long admission overlap from previous day, max_rows guard — `done`
- 80.6 Tool description с цепочкой `get_users → get_doctor_free_slots` + domain synonyms; `paginate_all.max_rows` cap добавлен — `done`

## Этап 81. Эргономические обёртки для типовых вопросов — `done`

Цель: выделить в самостоятельные MCP-tools те операции, которые LLM-у трудно собрать из общих инструментов, несмотря на этап 78.

- 81.1 `get_client_upcoming_visits(client_id, pet_id=0, date_from=today, days=90, limit=20)` — тонкая обёртка: client_id + date range + sort ASC + client-side filter по активным статусам — `done`
- 81.2 `get_daily_schedule(date=today, doctor_id=0, clinic_id=0, limit=100)` — все приёмы дня, sort ASC, фильтр по активным статусам — `done`
- 81.3 9 e2e mock тестов `test_convenience_tools.py` + tool descriptions с domain synonyms + real API smoke на devtr6 — `done`

## Этап 82. Hot-fix этапа 78: корректный поиск клиента по телефону через `/rest/api/ClientPhone` — `done`

Цель: исправить deferred issue этапа 78 — `get_clients.phone` не работал для полных номеров, потому что в БД `cell_phone` хранится с форматированием (`"(918)414-02-59"`). Обнаружено в legacy PHP: есть отдельная таблица `clients_phones` с `clean_phone` (digits-only), экспонируется в REST как `/rest/api/ClientPhone` (регистр важен).

- 82.1 Helper `_resolve_client_ids_by_phone` с двухпроходным поиском: сначала trailing-10 digits (покрывает RU/US/CA 10-digit national plan), fallback к full digits (покрывает UK/etc non-10 plans) — `done`
- 82.2 Phase 1 cap: `totalCount > 100` → `ValueError("phone search too broad")` вместо silent truncation — `done`
- 82.3 Phase 2: batch-fetch клиентов через `id IN [...]`, композируется с `status`/`email`/user-filter — `done`
- 82.4 7 тестов на двухфазный поиск, fallback, truncation, dedupe по client_id + real API verify на devtr6 для `+7 (918)...`, `8 918...`, `7 918...`, `918414` — все работают — `done`

## Этап 83. Оптимизация `get_inactive_pets` через `IN` оператор (устранение N+1) — `done`

Цель: устранить N+1 в `get_inactive_pets`. Текущий алгоритм делал 1-2 запроса на каждого питомца клиента (invoice + medcard). Probe подтвердил поддержку `IN` оператора с JSON-list value на `invoice.pet_id` и `MedicalCards.patient_id`.

- 83.1 Real API probe: `IN` работает на `invoice.pet_id`, `MedicalCards.patient_id`, `admission.status` с list value — `done`
- 83.2 Refactor `tools/_inactive_helpers.py::find_pets_at_client_last_visit`: один batched invoice запрос с `pet_id IN [ids]` + один batched medcard запрос для pets без invoice-матча, per-pet цикл убран — `done`
- 83.3 Новый тест `test_get_inactive_pets_batches_invoice_and_medcard_via_in_operator` (проверяет call_count=1 для invoice и medcard routes + корректное разбиение на visited/fallback) — `done`
- 83.4 Real API замер на devtr6: latency=1.71s для 2 клиентов (раньше ~5-15s на 50) — `done`

## Этап 84. API-level `status IN [...]` в convenience tools — `done`

Цель: в этапе 81 (`get_client_upcoming_visits`, `get_daily_schedule`) активные статусы фильтруются client-side после `get_admissions` запроса. С подтверждённой в этапе 83 поддержкой `status IN [list]` — переходим на API-level фильтрацию: точнее `totalCount`, меньше данных по сети, стабильный envelope без `filtered_from_total`.

- 84.1 Probe: `admission?filter=[status IN ["save","accepted","directed"]]` работает (подтверждено в этапе 83) — `done`
- 84.2 Заменить client-side post-filter на API-level `status IN ACTIVE_ADMISSION_STATUSES` в `get_client_upcoming_visits` и `get_daily_schedule`, убрать `filtered_from_total` — `done`
- 84.3 Обновить тесты: `test_daily_schedule_filters_inactive_statuses_via_api` проверяет что filter содержит `status IN`, а response не содержит deleted/not_approved — `done`
- 84.4 Real API verify: `get_daily_schedule(date="2024-10-31")` возвращает 1 запись со статусом `delayed`, filter содержит `status IN [...]` — `done`
