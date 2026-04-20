# Этап 66. Ревью использования ресурсов API Vetmanager

## Цель

Проверить, что кеширование на стороне сервиса эффективно работает, и минимизировать лишние запросы к upstream API.

---

## 66.1 Аудит request_cache.py

### Архитектура кеша

`InMemoryTaggedCache` — dict-based storage с tag-индексом для инвалидации.
- Ключ: `"GET|{canonical_url}|{api_key_fingerprint}"`
- Значения: deep copy при чтении и записи (предотвращает мутацию)
- Конкурентность: asyncio.Lock — безопасно

### TTL-стратегия — OK

| Тип данных | TTL | Entities |
|---|---|---|
| Справочные (stable) | 900s (15 мин) | breed, petType, city, cityType, street, unit, role, userPosition, comboManualName, comboManualItem |
| Мутабельные | 60s (1 мин) | admission, client, pet, invoice, payment, medicalcard |

### Инвалидация — MEDIUM: overly broad

POST/PUT/DELETE инвалидируют ВСЕ записи entity по тегу `"{domain}:{entity}"`.

Пример: `PUT /rest/api/client/123` инвалидирует кеш для ВСЕХ client-запросов (list с разными фильтрами, другие client by id). Это создаёт холодный кеш после любой мутации.

Для текущей нагрузки приемлемо, но при росте числа пользователей станет bottleneck.

### Hit/miss metrics — GAP: нет метрик

Нет счётчиков hit/miss, нет eviction tracking. Невозможно оценить эффективность кеша.

### Memory bounds — HIGH: кеш может расти безлимитно

- Нет max size
- Нет LRU eviction
- Cleanup только при проверке TTL
- При уникальных комбинациях filter/sort/offset — разные cache keys → рост памяти

## 66.2 Аудит vetmanager_client.py

### Кеширование GET — OK

Все GET-запросы проходят через кеш (vetmanager_client.py:230–235). Canonical URL с отсортированными параметрами обеспечивает стабильные ключи.

### N+1 проблемы — HIGH

| Tool | Файл:строка | API calls | Проблема |
|---|---|---|---|
| `get_medical_cards_by_client_id` | medical_card.py:102–130 | 1 + N (N = число питомцев) | Для каждого питомца отдельный запрос мед.карт |
| `get_client_profile` | client.py:227–303 | 4 sequential | client + invoices + admissions + next_admission |
| `get_pet_profile` | pet.py:149–225 | 3 sequential | pet + medical_cards + vaccinations |
| `get_debtors` | client.py:49–118 | N pages | Pagination loop, каждая страница = запрос |
| `get_average_invoice` | invoice.py:51–123 | N pages | Pagination loop |

### Неиспользованная параллелизация

`get_client_profile` и `get_pet_profile` делают 3–4 последовательных GET-запроса которые могли бы выполняться через `asyncio.gather()`.

### Rate limiting к upstream — OK

0.05s (50ms) gap между запросами. Per-client instance. При N+1 это становится 50ms * N — get_medical_cards_by_client_id с 50 питомцами = 2.5 секунды чистого ожидания.

## 66.3 Все ли GET-запросы к справочным данным проходят через кеш

**Да.** Все tools в reference.py используют `VetmanagerClient().get()` который проходит через REQUEST_CACHE. Проверено для: breed, petType, city, cityType, street, unit, role, userPosition, comboManualName, comboManualItem.

## 66.4 Корректность инвалидации после мутаций

POST/PUT/DELETE корректно инвалидируют тег entity (vetmanager_client.py:259–260). Тег извлекается из URL по паттерну `/rest/api/{entity}`.

**Нюанс:** Инвалидация всех записей entity, а не конкретного ID — overly broad, но корректная. Нет случаев, когда мутация НЕ инвалидирует кеш.

## 66.5 Rate limiting к upstream API

Текущий 0.05s gap — приемлем для single-user сценариев. При параллельных запросах от нескольких пользователей лимит per-instance, не global.

При N+1 паттернах rate limit amplifies проблему: каждый запрос в цикле ждёт 50ms.

## 66.6 Метрики кеша — GAP

Нет Prometheus метрик для кеша. Рекомендация:
- `cache_hits_total` (counter)
- `cache_misses_total` (counter)
- `cache_invalidations_total` (counter, label: entity)
- `cache_size_entries` (gauge)

## 66.7 Bulk-запросы и prefetch

Vetmanager API не поддерживает batch/bulk endpoints. Но можно:
1. **Параллелизация:** `asyncio.gather()` для profile tools (3–4 запроса одновременно)
2. **Умный prefetch:** При запросе client_profile подгружать pets в кеш для последующего get_pet_profile
3. **Consolidation:** get_medical_cards_by_client_id — вместо N запросов по питомцам, один запрос с filter по client_id (если API поддерживает)

## 66.8 Сводный отчёт

| # | Severity | Проблема | Рекомендация |
|---|---|---|---|
| R1 | HIGH | Кеш без max size / LRU eviction | Добавить max_entries и LRU |
| R2 | HIGH | N+1 в get_medical_cards_by_client_id (1+N calls) | Проверить filter по client_id на API, или кешировать по-другому |
| R3 | MEDIUM | Нет метрик кеша (hit/miss/size) | Добавить Prometheus counters |
| R4 | MEDIUM | Profile tools не параллелизированы (3–4 sequential) | asyncio.gather() |
| R5 | MEDIUM | Overly broad invalidation (весь entity tag) | Приемлемо пока, мониторить после R3 |
| R6 | LOW | Pagination queries не кешируются эффективно | Каждый offset = отдельный ключ, expected behavior |
