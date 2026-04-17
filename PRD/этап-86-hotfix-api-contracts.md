# Этап 86. Hot-fix: create_admission + get_medical_cards_by_client_id

## Контекст

Baseline super-review 2026-04-17 (`artifacts/review/2026-04-17-baseline-post-stage-84.md`) выявил два product-blocker'а: оба tool'а вызывают API с неправильными именами полей и молча возвращают ошибочный результат (приём невидим в расписании, медкарты клиента всегда пустые). Ошибки подтверждены против `vetmanager-extjs` и `support-bot-base/base/vetmanager_help/REST_API/` (см. чеклист в `artifacts/api-research-notes-ru.md`).

## Цель

Починить оба tool'а так, чтобы:
- `create_admission` создавал видимый приём со статусом `save` (дефолт) и попадал в `get_daily_schedule` / `get_client_upcoming_visits`
- `get_medical_cards_by_client_id` возвращал медкарты всех питомцев клиента за ≤2 API-запроса (вместо N+1)

Внешние имена параметров MCP-tools не меняются (`doctor_id`, `date`, `pet_id`) — мапим на правильные API-поля внутри. Это избегает breaking change для LLM-клиентов.

## Scope

**В scope:**
- `tools/admission.py::create_admission` — fix payload
- `tools/medical_card.py::get_medical_cards_by_client_id` — fix filter + N+1

**Вне scope (отдельные этапы):**
- `tools/pet.py::create_pet` использует `client_id` вместо `owner_id` — **этап 87** (post-migration sweep)
- `tools/invoice.py::create_invoice` — требует отдельной проверки invoice entity в ExtJS
- `prompts.py::book-appointment` — **этап 87** (prompts sweep)

## Подзадачи

### 86.1 create_admission: payload mapping

Файл: `tools/admission.py:298-326`.

Текущее: payload `{pet_id, client_id, doctor_id, date, status, reason}`, default `status='assigned'`.

Фикс:
```python
payload = {
    "patient_id": pet_id,       # внешнее имя → API поле
    "client_id": client_id,     # без изменений
    "user_id": doctor_id,       # внешнее имя → API поле
    "admission_date": date,     # внешнее имя → API поле
    "status": status,
}
if reason:
    payload["reason"] = reason
```

Дефолт `status`: `save` (реальный дефолт из `Entity/Admission.php`). Обновить docstring: перечислить реальные значения enum + убрать `'assigned'`/`'booked'` (их нет).

LOC: ≤20.

### 86.2 get_medical_cards_by_client_id: owner_id + IN batch

Файл: `tools/medical_card.py:58-134`.

Текущее:
- Step 1 фильтр pets: `{"property": "client_id", "value": ...}` — возвращает пусто (Pet FK = owner_id)
- Step 2: N+1 цикл по pet_ids — для клиента с 5 питомцами делает 5 отдельных медкарт-запросов

Фикс:
- Step 1: `{"property": "owner_id", "value": str(client_id), "operator": "="}`
- Step 2: один запрос с `{"property": "patient_id", "value": pet_ids, "operator": "IN"}` вместо цикла (паттерн из этапа 83)

LOC: ≤30.

### 86.3 Тесты (test-first)

Добавить в `tests/test_e2e_mock_entities.py` или новый `tests/test_api_contracts_hotfix.py`:

**`test_create_admission_uses_patient_id_user_id_admission_date`**:
- mock `POST /rest/api/admission` через respx, захватить body
- вызов через `mcp.call_tool("create_admission", {pet_id, client_id, doctor_id, date, status})`
- assert body содержит `{patient_id, user_id, admission_date}` и НЕ содержит `{pet_id, doctor_id, date}`
- assert default status = `save`

**`test_create_admission_rejects_invalid_status`** (опционально — смотреть что VM вернёт; пока skip если API не валидирует strict):
- можно ограничиться проверкой что docstring перечисляет правильный enum

**`test_get_medical_cards_by_client_id_uses_owner_id_filter`**:
- mock `GET /rest/api/pet` с `filter=[owner_id=...]`, возвращает 3 питомца
- assert первый вызов был с `"property": "owner_id"`

**`test_get_medical_cards_by_client_id_batches_medcard_via_in`**:
- mock `GET /rest/api/pet` → 3 питомца (id 1, 2, 3)
- mock `GET /rest/api/MedicalCards` с `filter=[patient_id IN [1,2,3]]` → 4 медкарты
- assert medcard endpoint вызван **ровно 1 раз** (call_count == 1), не 3
- assert response `medical_cards_count == 4`, `pets_count == 3`

Обновить существующий `test_create_admission` и `test_get_medical_cards_by_client_id` (раньше они проверяли неправильный контракт через raw client, сейчас — через `mcp.call_tool`).

LOC: ≤120.

### 86.4 Regression check

Grep по `tools/` на паттерн `{"property": "client_id".*"pet"` и `{"property": "pet_id".*"admission|MedicalCards"` — убедиться что остались только корректные usage (filter на admission/invoice/clientPhone — client_id корректен; filter на pet/medical_cards — только owner_id/patient_id).

Никаких изменений — просто подтверждение scope'а.

### 86.5 Run tests

```bash
docker compose --profile test run --rm test
```

Все 26+ тестов должны пройти, новые 3-4 тоже.

### 86.6 Codex review

Промпт с inline diff + PRD + API checklist (из `api-research-notes-ru.md`) + явное `patient_id != pet_id, user_id != doctor_id`. Лимит 2 итерации.

### 86.7 Коммит + push

Commit message: `Stage 86: hot-fix create_admission payload + medical_cards owner_id/IN`.

### 86.8 AssumptionLog + Roadmap

- AssumptionLog: раздел про mapping стратегию (внешние имена сохранены, внутри мапим)
- Roadmap: этап 86 `todo` → `done`

## Риски

- **Real API не валидирован в рамках этого этапа** — fix проверяется только mock-тестами. Real API smoke на devtr6 — желательно, но не блокер (этап 86.5 можно расширить).
- **Rollback**: изменения small и изолированные, откат — одиночный revert.

## Acceptance

- Новые тесты проходят
- Полный test suite зелёный
- Codex review — 0 адекватных critical findings после финальной итерации
- Docstring `create_admission` перечисляет реальные enum-значения status
