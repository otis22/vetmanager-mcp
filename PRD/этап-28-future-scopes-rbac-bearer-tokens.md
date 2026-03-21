# PRD: Этап 28. Future scopes / RBAC для Bearer-токенов

## Контекст

Bearer-only runtime уже реализован: токен идентифицирует account сервиса, а
активное Vetmanager-подключение определяется через account context.

Сейчас все Bearer-токены аккаунта фактически обладают одинаковым полным доступом
к MCP tools этого аккаунта. Для дальнейшего hardening нужна модель будущих прав,
которая:
- не ломает текущий bearer-only runtime;
- не требует немедленного enforcement на каждом tool;
- позволяет позже ввести ограничения по группам операций и типам методов.

## Цель этапа

Спроектировать и частично подготовить основу для прав Bearer-токенов:
- определить модель scopes / capability-based RBAC;
- зафиксировать coarse-grained scopes для первого релиза ограничений;
- подготовить storage/schema без обязательного enforcement в этом этапе;
- синхронизировать архитектурные артефакты.

## Нецели

- Не внедрять полноценный runtime enforcement на всех tools.
- Не менять текущий UX выпуска токенов в web UI.
- Не строить per-user/per-account role system поверх Bearer-токенов.
- Не добавлять fine-grained ACL на уровне отдельных полей, clinic IDs или record IDs.

## Решение

### 1. Модель прав

Выбирается capability-модель на уровне Bearer-токена:
- права принадлежат токену, а не аккаунту;
- токен хранит список scopes;
- scope именуется как `<resource_group>.<action>`;
- отсутствие scope означает запрет после будущего enforcement;
- wildcard scope в storage не вводится на этом шаге, чтобы контракт был проще.

Это не полноценный enterprise RBAC с ролями, наследованием и субъектами.
Практически это token-scoped capability list с возможностью позже добавить
presets/roles как слой поверх scopes.

### 2. Coarse-grained scope groups первого релиза

Для первого будущего enforcement достаточно coarse-grained групп:
- `clients.read`
- `clients.write`
- `pets.read`
- `pets.write`
- `admissions.read`
- `admissions.write`
- `medical_cards.read`
- `medical_cards.write`
- `finance.read`
- `finance.write`
- `inventory.read`
- `inventory.write`
- `users.read`
- `messaging.read`
- `messaging.write`
- `reference.read`
- `analytics.read`

Принцип группировки:
- `read` покрывает безопасные get/list/read-only tools;
- `write` покрывает create/update/send/other state-changing tools;
- reference/catalog endpoints собираются в `reference.read`;
- агрегирующие read-only профили и отчётные tools идут в `analytics.read`.

### 3. Совместимость

Чтобы не сломать существующие токены и клиентов:
- enforcement в runtime не включается в этом этапе;
- новые токены получают default full-access набор всех coarse-grained scopes;
- старые токены без сохранённого scope manifest интерпретируются как
  `legacy full-access` до момента явной миграции UI/API.

### 4. Storage/schema prep

В `service_bearer_tokens` добавляется:
- `access_policy_version` — версия схемы прав;
- `scopes_json` — сериализованный список scopes токена.

На уровне модели добавляются helper’ы:
- нормализация scopes;
- сериализация/десериализация;
- default full-access manifest;
- безопасный fallback для legacy tokens без `scopes_json`.

## Декомпозиция

### 28.1 Спроектировать модель scopes / RBAC
- Зафиксировать token-scoped capability model.
- Описать naming convention и правила совместимости.

### 28.2 Зафиксировать coarse-grained scopes
- Утвердить список scopes первого будущего enforcement-релиза.
- Добавить нормализацию и default full-access manifest.

### 28.3 Подготовить storage/schema
- Расширить `ServiceBearerToken`.
- Добавить Alembic migration.
- Обновить token issue path для записи policy metadata.
- Добавить unit/migration tests.

### 28.4 Обновить артефакты
- Обновить `Roadmap.md`.
- Обновить `artifacts/technical-requirements-vetmanager-mcp-ru.md`.
- Зафиксировать решения в `AssumptionLog.md`.

## Acceptance Criteria

- В кодовой базе есть единый список поддерживаемых coarse-grained scopes.
- `ServiceBearerToken` умеет хранить и отдавать scope manifest.
- Новые токены получают default full-access scopes.
- Legacy токены без scope manifest остаются совместимыми.
- Alembic `upgrade head` создаёт/обновляет схему с новой policy metadata.
- Добавлены unit/migration tests.
- Артефакты синхронизированы с выбранной моделью.
