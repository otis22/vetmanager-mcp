# PRD: Этап 20. Bearer-only архитектура и артефакты

## Цель

Зафиксировать продуктовый переход от текущего headers-only MCP runtime к
bearer-only модели сервиса, где MCP-клиент аутентифицируется через
`Authorization: Bearer <service_token>`, а credentials Vetmanager хранятся и
выбираются на уровне аккаунта сервиса.

## Проблема

- Текущий код проекта всё ещё использует headers-only контракт
  `X-VM-Domain` / `X-VM-Api-Key`.
- В roadmap уже начат следующий цикл продукта, но до этой задачи у него не
  было отдельного PRD-файла с декомпозицией и границами работ.
- Без отдельного PRD следующие этапы 21–28 рискуют смешать текущую реализацию
  с целевой архитектурой и потерять чёткий контракт между account layer,
  bearer auth и Vetmanager integration layer.

## Основания

- [Roadmap.md](../Roadmap.md): этапы 20–28 уже определяют bearer-only
  направление и дальнейшие зависимости.
- [artifacts/prd-vetmanager-mcp-ru.md](../artifacts/prd-vetmanager-mcp-ru.md):
  продуктовый PRD уже переведён на bearer-only целевую auth-модель.
- [artifacts/technical-requirements-vetmanager-mcp-ru.md](../artifacts/technical-requirements-vetmanager-mcp-ru.md):
  технический артефакт уже фиксирует двухслойную картину
  "текущая реализация + планируемая эволюция".

## Границы этапа

- Этап 20 является planning/artifacts этапом.
- В рамках этого этапа не требуется менять runtime-код MCP-сервера, storage,
  web-слой или существующие инструменты.
- Результатом этапа должны стать согласованные артефакты, по которым можно
  безопасно начинать этапы 21+ без возврата к product-discovery.

## Целевая модель

1. Пользователь работает не напрямую с headers runtime credentials, а через
   аккаунт сервиса.
2. Аккаунт хранит ровно один активный способ авторизации в Vetmanager.
3. Bearer-токены принадлежат аккаунту и используются MCP-клиентами как
   единственный runtime credential.
4. Сервис по Bearer определяет аккаунт, находит активную Vetmanager-интеграцию
   и только затем выполняет вызовы Vetmanager API.
5. Dual-mode runtime не планируется: bearer-only модель должна заменить
   текущий headers-only контракт, а не сосуществовать с ним бесконечно.

## Доменная модель

- `account`
  Владелец сервиса, web-кабинета, Vetmanager-интеграции и Bearer-токенов.
- `vetmanager_connection`
  Активный способ подключения аккаунта к Vetmanager.
  На первом шаге приоритетен `domain + rest_api_key`, позже добавляется
  `user login/password -> user token`.
- `service_bearer_token`
  Runtime credential MCP-клиента. Хранит статус, TTL, revoke state, безопасный
  `token_prefix` для UI и hash полного секрета.
- `token_usage_stats` / `token_usage_log`
  Учёт эксплуатации токенов: `last_used_at`, `request_count`, audit trail.

## Декомпозиция

### 20.1 PRD этапа
- Создать отдельный PRD-файл для bearer-only цикла.
- Зафиксировать границы этапа: planning only, без runtime implementation.

### 20.2 Синхронизация главных артефактов
- Обновить продуктовый PRD и technical requirements под bearer-only направление.
- Убедиться, что roadmap, PRD и technical requirements не противоречат друг
  другу по auth-модели, runtime contract и терминологии.

### 20.3 Доменная модель
- Зафиксировать минимальный набор сущностей:
  `account`, `vetmanager_connection`, `service_bearer_token`,
  `token_usage_stats` / `token_usage_log`.
- Развести ownership между account layer и Vetmanager integration layer.

### 20.4 Контракт авторизации
- Зафиксировать правило: Bearer-токен привязан к аккаунту, а не к отдельной
  Vetmanager-сессии или MCP workspace.
- Зафиксировать правило: аккаунт хранит ровно один активный способ
  авторизации в Vetmanager в каждый момент времени.

### 20.5 Стратегия миграции
- Зафиксировать, что dual-mode не поддерживается как постоянная архитектура.
- Bearer-only рассматривается как следующая фаза продукта с последующей
  заменой текущего headers-only runtime.

### 20.6 Фиксация решения
- Обновить `AssumptionLog.md`.
- Перевести этап 20 в `done` после появления PRD и согласованных артефактов.

## Критерии готовности

- В `PRD/` существует отдельный документ этапа 20.
- `Roadmap.md`, главный PRD и technical requirements согласованы по
  bearer-only направлению.
- Доменная модель и ограничения bearer-only архитектуры зафиксированы явно.
- Решение задокументировано в `AssumptionLog.md`.
