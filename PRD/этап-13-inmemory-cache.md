# PRD Этап 13: In-memory тегированный кеш GET

## Цель
Добавить в `VetmanagerClient` in-memory кеш для всех исходящих GET-запросов к Vetmanager API с TTL 15 минут, ключом на основе метода/полного URL/query и hash API-ключа, а также теговой инвалидацией на мутациях (`POST`/`PUT`/`DELETE`).

## Контекст
- Проект уже перешёл на headers-only credentials и security hardening (этап 12).
- Сейчас каждый GET идёт напрямую во внешний API, даже при одинаковых повторных запросах.
- Нужен простой кэш в памяти процесса без внешнего хранилища.

## Контракт кеша
- Кешируются только успешные GET-ответы.
- TTL записи: `900` секунд (15 минут).
- Ключ кеша: `METHOD + canonical_full_url_with_sorted_query + sha256(api_key)[:N]`.
- Тег записи: `domain:entity`, где `entity` извлекается из URL пути (`/rest/api/<entity>/...`) и нормализуется в lower-case.
- При успешном `POST`/`PUT`/`DELETE` по сущности выполняется инвалидация всех записей по тегу `domain:entity`.

## Декомпозиция задач

### 13.1 Артефакты и требования
- Обновить `Roadmap.md` и `artifacts/prd-vetmanager-mcp-ru.md`.
- Описать кеш-контракт и ограничения in-memory подхода.
- <= 80 LOC.

### 13.2 Тесты (Red)
- Добавить/обновить unit-тесты:
  - cache hit для повторного GET;
  - истечение TTL;
  - изоляция по `api_key_hash`;
  - инвалидация по тегу на POST/PUT/DELETE;
  - извлечение entity из стандартных и нестандартных путей.
- <= 150 LOC.

### 13.3 Реализация кеш-хранилища
- Отдельный модуль `request_cache.py`:
  - in-memory `dict` + tag index;
  - `asyncio.Lock`;
  - операции `get`, `set`, `invalidate_tag`, `cleanup_expired`.
- <= 150 LOC.

### 13.4 Интеграция в `VetmanagerClient`
- Применить кеш в GET-потоке.
- Применить tag invalidation после успешных мутаций.
- Сохранить совместимость с текущими retry/pacing/security.
- <= 150 LOC.

### 13.5 Документация и фиксация решений
- Обновить `README.md`.
- Обновить `AssumptionLog.md`.
- Закрыть этап 13 в `Roadmap.md`.
- <= 80 LOC.

## Критерии готовности
- Повторный GET по одинаковому ключу отдаётся из кеша в рамках TTL.
- Ключ учитывает query и hash API-ключа.
- Мутации сбрасывают кеш по тегу `domain:entity`.
- Тесты зелёные в docker workflow.
- `README.md`, `AssumptionLog.md`, `artifacts/prd-vetmanager-mcp-ru.md` синхронизированы.
