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
