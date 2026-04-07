# PRD: Этап 54.2.1-54.2.2 — Redis backend для rate limiter и cache

## Цель
Подготовить инфраструктуру к multi-worker деплою через опциональный Redis backend.

## Архитектура

### Принцип
- **Опционально**: при отсутствии `REDIS_URL` работает текущий in-memory backend (zero impact на dev/single-process).
- **Backend abstraction**: factory выбирает реализацию по env var.
- **Graceful degradation**: если Redis недоступен — fallback на in-memory с WARNING log.

### Подзадачи

#### 54.2.1 Redis rate limiter
- Файл `rate_limit_backend.py` с интерфейсом RateLimitBackend (check, record, clear, reset)
- `InMemoryRateLimitBackend` (текущая логика, рефакторинг из web_security.py)
- `RedisRateLimitBackend` (Redis ZSET для скользящего окна)
- Factory `get_rate_limit_backend()` по REDIS_URL
- web_security.py использует backend через factory

#### 54.2.2 Redis cache
- Аналогично: `request_cache.py` уже имеет `InMemoryTaggedCache`
- Добавить `RedisTaggedCache` (Redis HASH/SET для tag индексов)
- Factory по REDIS_URL
- vetmanager_client использует абстрактный интерфейс

## Зависимости
- redis>=5.0.0,<6 (опциональная зависимость)
- fakeredis>=2.0.0,<3 (test-only)

## Тесты
- InMemory backends — текущие тесты (regression)
- Redis backends — через fakeredis
- Factory selection — env var → backend type
- Fallback при недоступности Redis
