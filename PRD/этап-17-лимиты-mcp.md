# PRD Этап 17: Лимиты в inputSchema (limit 1–100)

## Цель
В ответе MCP `tools/list` у всех инструментов с параметром `limit` в `inputSchema.properties.limit` должны быть `minimum: 1`, `maximum: 100` и осмысленное описание, чтобы клиенты MCP (и LLM) не передавали невалидные значения и не получали ошибку от Vetmanager API.

## Контекст
- Ограничение 1–100 задано Vetmanager REST API.
- Runtime-валидация уже есть в `validate_list_params()` (этап 8); при limit > 100 выбрасывается `ValueError`.
- Схема, которую сервер отдаёт в `tools/list`, не содержит min/max для `limit` — LLM и клиенты не видят ограничений и могут передавать, например, `limit=200`.

## Декомпозиция

### 17.1 Константы и тип LimitParam в validators
- В `validators.py`: импорт `Annotated`, `Field` из pydantic.
- Экспорт константы `VETMANAGER_MAX_LIMIT` (алиас к `_LIMIT_MAX`).
- Тип `LimitParam = Annotated[int, Field(ge=1, le=_LIMIT_MAX, description="Max records to return (1–100).")]` — чтобы FastMCP включал в JSON Schema поля minimum, maximum, description.

### 17.2 Замена limit: int на limit: LimitParam во всех get_*
- Во всех файлах `tools/*.py`, где есть get_* с параметром `limit`: добавить импорт `LimitParam` из validators; заменить `limit: int = 20` (или 50) на `limit: LimitParam = 20` (или 50).
- Файлы: client, pet, admission, medical_card, invoice, good, user, reference, finance, warehouse, clinical, operations.
- Инструменты без limit (*_by_id, create_*, update_*, get_client_profile, get_pet_profile) не трогать.

### 17.3 Тест/проверка tools/list
- Добавить тест (unit или e2e): вызов `tools/list` возвращает у инструмента с параметром limit в `inputSchema.properties.limit` поля `minimum: 1`, `maximum: 100` (и при необходимости непустое description).

### 17.4 Документация
- Запись в AssumptionLog.md: этап 17, решение про LimitParam и экспорт схемы.
- README при необходимости (упоминание лимита 1–100 в разделе про инструменты).

## Критерии приёмки
- Все get_* инструменты с параметром limit отдают в schema limit с minimum=1, maximum=100.
- Тесты vetmanager-mcp проходят.
- Запись в AssumptionLog.
