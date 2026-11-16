# Review этапа 462 — working diff, 16.11.2026

Объект: рабочий diff ветки `dev/roadmap-462-scalar-projection` от `e78f7603cde60d6eba3128b70da070a1b816d542`; snapshot SHA-256 `c7e8bfefa0d2be2c432e169ce9f7519b5cfb9bf623972a216d6f5d21dd6b9f55`. Scope: changed + связанные `get_clients`, OpenAPI, список прав и тесты проекции. Production повторно не читался; факт формы — обезличенный снимок куратора.

## Coverage

- Код и архитектура: локальное распознавание `client_type_data:object|null`; публичный `include` не расширен.
- Простота: одно правило в существующем проекторе, без новой абстракции/REST-вызова.
- Документы и продукт: PRD и Architecture Critique связывают повтор #150/#161 с конкретной формой; devtr6 — проверка совместимости.
- Безопасность и права: scalar не выдаёт вложенный объект; неизвестная вложенность при `include` по-прежнему отклоняется; реестр прав не менялся.
- Производительность и надёжность: число REST-вызовов, лимиты, порядок и `totalCount` не меняются.
- Наблюдаемость: новых логов и клиентских значений в evidence нет.
- Тесты и слепые зоны: 13 синтетических cases, в том числе неверные типы, nullable, соседний инструмент, маска, пагинация; новый тип объекта внутри не выдумывается.

## Вердикты

Spark candidate-only: `findings=[]`, прочитано 11 файлов, `stage462/spark-prefreeze.result.txt`. Astra valid 1/2: `findings=[]`, validator exit 0, `stage462/astra-prefreeze-attempt-1-of-3.result.json`. Opus valid 1/2: один medium — тест запрета `fields/include=['client_type_data']` ловил любой `Exception`. Принято; теперь проверяются `ToolInputError` и точные сообщения. Envelope и сведение — в `AssumptionLog.md`. Совпавших findings нет, отклонённых нет, открытых critical/high нет.

После исправления: focused 13 passed, owning 56 passed, fast 3416 passed. Полный default — 4848 passed, manifest complete; живой read-only вызов на devtr6 — REST 200, MCP `is_error=false`, одна строка только с `id/status`. Real aggregate дал 118 passed / 1 failed / 19 skipped-not-configured: единственный failure в stage276 export, machine code `NOT_FOUND` при получении файла после успешного start. Это другой инструмент и не установлено, связан ли отказ с правкой 462. Куратор разрешил один retry poll/download только существующего file ID: адресный вызов завершился success, `rows=1`, `columns=1`, `depersonalized=true`, файл присутствовал. Первоначальный aggregate exit 1 сохранён; вместе с 118 passed и successful focused download это составное evidence закрывает real gate по решению куратора. Причина прежнего `NOT_FOUND` неизвестна. Подробности — в `AssumptionLog.md`; committed-diff review следует после commit.
