# Vetmanager REST API: матрица CRUD-операций по сущностям

**Версия:** 1.0
**Дата:** 26 марта 2026 г.
**Источник:** анализ контроллеров `vetmanager-extjs/rest/protected/controllers/`

## Принцип работы

Базовый класс `ERestController` предоставляет **полный CRUD по умолчанию** (list, view, create, update, delete). Контроллеры ограничивают доступ двумя способами:

1. **`filterRestAccessRules()`** — белый список разрешённых actions (например `restList, restView` = только чтение)
2. **Переопределение `doRest*` методов** — кастомная логика (валидация, обогащение данных)

Пустые контроллеры (без переопределений) наследуют полный CRUD.

---

## Матрица операций

### Условные обозначения

- **+** — операция разрешена и реализована
- **+(i)** — операция доступна через наследование от базового класса (пустой контроллер)
- **-** — операция явно запрещена через `filterRestAccessRules`
- **custom** — нестандартная реализация (не REST CRUD)

---

### Основные сущности (используются в MCP)

| Сущность | GET list | GET by id | POST create | PUT update | DELETE | Ограничение | Файл контроллера |
|----------|----------|-----------|-------------|------------|--------|-------------|------------------|
| **Client** | +(i) | + | + | +(i) | + | нет | ClientController.php |
| **Pet** | +(i) | +(i) | + | +(i) | +(i) | нет | PetController.php |
| **Admission** | + | + | + | + | **-** | restList, restView, restCreate, restUpdate | AdmissionController.php |
| **MedicalCards** | +(i) | +(i) | + | + | **-** | restList, restView, restCreate, restUpdate | MedicalCardsController.php |
| **Invoice** | + | + | + | + | + | restList, restView, restCreate, restUpdate, restDelete | InvoiceController.php |
| **InvoiceDocument** | +(i) | + | +(i) | +(i) | +(i) | нет | InvoiceDocumentController.php |
| **Payment** | +(i) | +(i) | **-** | **-** | **-** | restList, restView | PaymentController.php |
| **ClosingOfInvoices** | + | +(i) | **-** | **-** | **-** | restList, restView | ClosingOfInvoicesController.php |
| **Good** | + | +(i) | +(i) | +(i) | +(i) | filterRestAccessRules закомментирован | GoodController.php |
| **User** | +(i) | + | **-** | + | **-** | restList, restView, restUpdate | UserController.php |
| **Hospital** | + | + | **-** | + | **-** | restList, restView, restUpdate | HospitalController.php |
| **HospitalBlock** | + | +(i) | **-** | **-** | **-** | restList, restView | HospitalBlockController.php |
| **Clinics** | + | +(i) | +(i) | +(i) | +(i) | нет | ClinicsController.php |
| **Timesheet** | + | +(i) | + | +(i) | +(i) | нет | TimesheetController.php |
| **Suppliers** | +(i) | +(i) | + | + | **-** | restList, restView, restCreate (update реализован, но не в whitelist) | SuppliersController.php |
| **Messages** | — | — | — | — | — | custom: POST /messages/all, /messages/users, /messages/roles, GET /messages/reports | MessagesController.php |

### Справочные сущности

| Сущность | GET list | GET by id | POST create | PUT update | DELETE | Ограничение | Файл контроллера |
|----------|----------|-----------|-------------|------------|--------|-------------|------------------|
| **Breed** | + | +(i) | +(i) | +(i) | +(i) | нет | BreedController.php |
| **PetType** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | PetTypeController.php |
| **City** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | CityController.php |
| **CityType** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | CityTypeController.php |
| **Street** | + | +(i) | +(i) | +(i) | +(i) | нет | StreetController.php |
| **Unit** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | UnitController.php |
| **Role** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | RoleController.php |
| **UserPosition** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | UserPositionController.php |
| **ComboManualName** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | ComboManualNameController.php |
| **ComboManualItem** | +(i) | +(i) | + | +(i) | +(i) | нет | ComboManualItemController.php |

### Финансовые и складские сущности

| Сущность | GET list | GET by id | POST create | PUT update | DELETE | Ограничение | Файл контроллера |
|----------|----------|-----------|-------------|------------|--------|-------------|------------------|
| **Cassa** | +(i) | +(i) | **-** | **-** | **-** | restList, restView | CassaController.php |
| **CassaClose** | +(i) | +(i) | +(i) | +(i) | +(i) | filterRestAccessRules только авторизация | CassacloseController.php |
| **GoodGroup** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | GoodGroupController.php |
| **GoodSaleParam** | +(i) | +(i) | +(i) | +(i) | +(i) | нет (пустой) | GoodSaleParamController.php |
| **PartyAccount** | +(i) | +(i) | **-** | **-** | **-** | restList, restView | PartyAccountController.php |
| **PartyAccountDoc** | +(i) | +(i) | **-** | **-** | **-** | restList, restView | PartyAccountDocController.php |
| **StoreDocument** | +(i) | +(i) | **-** | **-** | **-** | restList, restView | StoreDocumentController.php |
| **Properties** | +(i) | +(i) | **-** | **-** | **-** | restList, restView | PropertiesController.php |

---

## Сводка: что реально можно добавить в MCP

### Можно реализовать (API разрешает)

| Сущность | Недостающая операция в MCP | API поддерживает |
|----------|---------------------------|------------------|
| **Client** | delete | + (DELETE разрешён) |
| **Pet** | update, delete | + (полный CRUD через наследование) |
| **Invoice** | update, delete | + (полный CRUD явно разрешён) |
| **InvoiceDocument** | create, update, delete | + (полный CRUD через наследование) |
| **Hospital** | update | + (PUT разрешён) |
| **User** | update | + (PUT разрешён) |
| **Timesheet** | create | + (POST реализован) |
| **Good** | create, update, delete | + (filterRestAccessRules закомментирован — CRUD доступен) |
| **GoodGroup** | create, update, delete | + (полный CRUD через наследование) |
| **GoodSaleParam** | create, update, delete | + (полный CRUD через наследование) |
| **Suppliers** | create, update | + (POST и PUT реализованы) |
| **CassaClose** | create, update, delete | + (полный CRUD через наследование) |
| **ComboManualItem** | create | + (POST реализован) |
| **Clinics** | create, update, delete | + (полный CRUD через наследование) |
| **Breed** | create, update, delete | + (полный CRUD через наследование) |

### Нельзя реализовать (API запрещает)

| Сущность | Запрещённая операция | Причина |
|----------|---------------------|---------|
| **Admission** | delete | явно запрещён в filterRestAccessRules |
| **MedicalCards** | delete | явно запрещён в filterRestAccessRules |
| **Payment** | create, update, delete | только restList + restView |
| **ClosingOfInvoices** | create, update, delete | только restList + restView |
| **Cassa** | create, update, delete | только restList + restView |
| **PartyAccount** | create, update, delete | только restList + restView |
| **PartyAccountDoc** | create, update, delete | только restList + restView |
| **StoreDocument** | create, update, delete | только restList + restView |
| **Properties** | create, update, delete | только restList + restView |
| **HospitalBlock** | create, update, delete | только restList + restView |
| **Hospital** | create, delete | явно запрещены в filterRestAccessRules |
| **User** | create, delete | явно запрещены в filterRestAccessRules |
| **Suppliers** | delete | не в whitelist (update реализован но формально не в whitelist — проверить на практике) |

---

## Примечания

1. **Пустые контроллеры** наследуют полный CRUD от `ERestController`. Это означает, что справочники (Breed, PetType, City, Role и т.д.) технически поддерживают запись, но на практике это может быть нежелательно — модификация справочников через MCP-инструменты требует осторожности.

2. **Suppliers.update** — метод `doRestUpdate` реализован в контроллере, но `restUpdate` отсутствует в whitelist `filterRestAccessRules`. Поведение зависит от реализации: если filter проверяет whitelist строго, update будет заблокирован. Требуется практическая проверка.

3. **Good** — `filterRestAccessRules` закомментирован в коде, что де-факто открывает полный CRUD. Однако это может быть временное состояние — следить за обновлениями.

4. **Payment** — только чтение через REST API. Создание и управление оплатами происходит через внутренние механизмы Vetmanager (UI, интеграции), не через REST.

5. **StoreDocument, PartyAccount, PartyAccountDoc** — складские документы доступны только на чтение. Создание происходит через бизнес-логику системы (приёмка, списание, перемещение).
