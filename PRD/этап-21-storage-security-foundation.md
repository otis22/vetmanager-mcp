# PRD: Этап 21. Storage и security foundation для Bearer-сервиса

## Цель

Подготовить инфраструктурную основу для bearer-only сервиса: выбрать и
внедрить БД для аккаунтов, Vetmanager-интеграций и Bearer-токенов, а также
заложить техническую базу для последующих миграций, безопасного хранения
секретов и lifecycle Bearer-токенов.

## Проблема

- Текущий проект является stateless MCP-обёрткой без persistence-слоя.
- Следующие этапы roadmap (`22+`) требуют account-based auth context, lookup
  Bearer-токена, хранение Vetmanager credentials и usage accounting.
- Без введения storage foundation невозможно перейти от headers-only runtime
  к bearer-only архитектуре.

## Границы этапа

- Этап 21 подготавливает persistence foundation.
- На шаге `21.1` выбирается и внедряется БД как технологическая база.
- Миграции схемы, секреты, hash Bearer-токенов и revoke/expiry lifecycle
  остаются отдельными задачами `21.2–21.5`.
- На этом этапе не требуется переводить runtime MCP auth на Bearer.

## Решение

1. Взять `SQLAlchemy 2.x` как основной persistence toolkit.
2. Использовать async engine/session, чтобы storage слой естественно
   встраивался в текущий async runtime и будущий web/auth flow.
3. Принять `SQLite` как локальный default для разработки и тестов, но
   конфигурацию строить через `DATABASE_URL`, чтобы без переписывания слоя
   перейти на production-grade PostgreSQL в следующих этапах.
4. Вынести storage foundation в отдельный модуль, не смешивая его с
   `VetmanagerClient` и текущими headers-only request helpers.

## Почему именно так

- `SQLAlchemy` даёт переносимую ORM/Core-базу и не привязывает проект
  к конкретной СУБД на раннем этапе.
- Async API согласуется с текущим стеком (`FastMCP`, `httpx`, async tests).
- SQLite позволяет быстро добавить persistence foundation без поднятия
  отдельного database container уже на `21.1`.
- Отдельный `DATABASE_URL` упрощает будущий переход на PostgreSQL и web-layer.

## Декомпозиция

### 21.1 Выбор и внедрение БД
- Добавить зависимости persistence layer.
- Реализовать базовый storage bootstrap:
  - нормализация `DATABASE_URL`;
  - async engine;
  - async session factory;
  - declarative base;
  - helper инициализации подключения.
- Покрыть выбор и bootstrap тестами.

### 21.2 Миграции
- Добавить миграционный инструмент и первую migration baseline для
  `accounts`, `vetmanager_connections`, `service_bearer_tokens`,
  `token_usage_stats` / `token_usage_logs`.

### 21.3 Секреты Vetmanager
- Спроектировать и реализовать безопасное хранение Vetmanager credentials.

### 21.4 Bearer token storage
- Хранить только hash Bearer-токена и безопасный `token_prefix`.

### 21.5 Lifecycle токенов
- Ввести срок действия, revoke и статусы Bearer-токенов.

### 21.6 Тесты persistence/security
- Покрыть persistence/security слой unit-тестами.

## Критерии готовности для 21.1

- В проекте есть отдельный storage-модуль с async DB foundation.
- Конфигурация БД берётся из `DATABASE_URL`.
- Для локальной разработки и тестов работает SQLite.
- Архитектура не блокирует дальнейший переход на PostgreSQL.
- Решение зафиксировано в `Roadmap.md` и `AssumptionLog.md`.
