# Этап 55. Расширение MCP-инструментов: недостающие CRUD-операции

## Цель

Довести покрытие CRUD-операций до максимума, разрешённого Vetmanager REST API.

**Источник истины:** `artifacts/api_crud_permissions-ru.md` — матрица CRUD по контроллерам.

---

## 55.1 Недостающие UPDATE-инструменты

### 55.1.1 `update_invoice`
- **Файл:** `tools/invoice.py`
- **Endpoint:** `PUT /rest/api/invoice/{id}`
- **Поля:** client_id, pet_id, description, status, percent, discount
- **Паттерн:** conditional payload, аналогично `update_client`

### 55.1.2 `update_user`
- **Файл:** `tools/user.py`
- **Endpoint:** `PUT /rest/api/user/{id}`
- **Поля:** last_name, first_name, middle_name, email, phone, cell_phone, position_id, role_id, is_active
- **Ограничения:** API запрещает create/delete

### 55.1.3 `update_hospitalization`
- **Файл:** `tools/clinical.py`
- **Endpoint:** `PUT /rest/api/hospital/{id}`
- **Поля:** date_out (end_date), description, status, block_id
- **Ограничения:** API запрещает create через POST (но у нас уже есть create_hospitalization — сверить)

### 55.1.4 `update_supplier`
- **Файл:** `tools/warehouse.py`
- **Endpoint:** `PUT /rest/api/Suppliers/{id}`
- **Поля:** company_name, contact_person, phone, mail, address, note, status
- **Примечание:** doRestUpdate реализован в контроллере, но не в whitelist — требует проверки на практике

### 55.1.5 Верификация существующих update-инструментов
- `update_pet` — добавить sex, color_id, chip_number, weight, status, owner_id
- `update_client` — добавить middle_name, cell_phone, address, city_id, status, note
- `update_admission` — добавить client_id, pet_id, clinic_id, type
- `update_medical_card` — проверить полноту

---

## 55.2 Недостающие DELETE-инструменты

### 55.2.1 `delete_client`
- **Файл:** `tools/client.py`
- **Endpoint:** `DELETE /rest/api/client/{id}`

### 55.2.2 `delete_pet`
- **Файл:** `tools/pet.py`
- **Endpoint:** `DELETE /rest/api/pet/{id}`

### 55.2.3 `delete_invoice`
- **Файл:** `tools/invoice.py`
- **Endpoint:** `DELETE /rest/api/invoice/{id}`

### 55.2.4 `delete_invoice_document`
- **Файл:** `tools/finance.py`
- **Endpoint:** `DELETE /rest/api/invoiceDocument/{id}`

**Общий паттерн DELETE:**
```python
async def delete_entity(entity_id: int) -> dict:
    vc = VetmanagerClient()
    return await vc.delete(f"/rest/api/entity/{entity_id}")
```

---

## 55.3 Недостающие CREATE-инструменты

### 55.3.1 `create_timesheet`
- **Файл:** `tools/operations.py`
- **Endpoint:** `POST /rest/api/timesheet`
- **Поля:** doctor_id (required), begin_datetime (required), end_datetime (required), clinic_id (required), title, type, shift

### 55.3.2 `create_good`
- **Файл:** `tools/good.py`
- **Endpoint:** `POST /rest/api/good`
- **Поля:** title (required), group_id, unit_storage_id, is_active, code, is_for_sale, prime_cost, description

### 55.3.3 `update_good`
- **Файл:** `tools/good.py`
- **Endpoint:** `PUT /rest/api/good/{id}`
- **Поля:** те же, что create, все optional

### 55.3.4 `create_supplier`
- **Файл:** `tools/warehouse.py`
- **Endpoint:** `POST /rest/api/Suppliers`
- **Поля:** company_name (required), contact_person, phone, mail, address, note, status

### 55.3.5 `create_invoice_document`
- **Уже реализовано** как `add_invoice_document` в `tools/finance.py` — верификация

---

## 55.4 Обновление существующих инструментов

Верифицировать полноту полей для:
- `update_client` — расширить набор полей
- `update_pet` — расширить набор полей
- `update_admission` — проверить полноту
- `update_medical_card` — проверить полноту

---

## 55.5 Документация ограничений

- Обновить README: какие операции недоступны и почему
- Обновить `artifacts/prd-vetmanager-mcp-ru.md` с учётом реальной матрицы CRUD
- Обновить `AssumptionLog.md`

---

## Ограничения по подзадачам

- Каждая подзадача ≤ 150 строк кода
- Каждый новый инструмент покрывается unit/mock тестом
