# PRD: Этап 41. Исправление user-token flow и ревизия e2e

## Цель

Синхронизировать backend, web UI, тесты и документацию с реальным Vetmanager contract для `login/password -> user token` exchange.

## Контекст

Этапы 26, 30 и 38 ввели рабочий `login/password -> user token` flow, но в
репозитории закрепилось ложное допущение: будто для `POST /token_auth.php`
нужен `X-REST-API-KEY`, а сам exchange можно безопасно моделировать как
`application/x-www-form-urlencoded` с зависимостью от `api_key`.

`Roadmap.md` фиксирует, что это нужно исправить и синхронизировать backend,
web UI, real/mock tests и документацию с реальным контрактом Vetmanager.

## Что подтверждено артефактами и внешней документацией

- В локальном `artifacts/vetmanager_openapi_v6.json` существует
  `POST /token_auth.php` с summary `Get Token (by User Login & Password)`.
- Тот же endpoint присутствует в
  `artifacts/vetmanager_postman_collection.json` как отдельный auth flow.
- В опубликованной Postman-документации Vetmanager для
  `Auth #3 (by User Login & Password -> Token)` указано:
  - request body: `form-data`;
  - поля: `login`, `password`, `app_name`;
  - для token exchange не показан `X-REST-API-KEY`;
  - дальнейшее использование токена идёт не через `X-REST-API-KEY`, а через
    `X-APP-NAME` + `X-USER-TOKEN`.

## Итоговый контракт этапа 41

### 1. Exchange endpoint

- Endpoint: `POST {resolved_host}/token_auth.php`
- Формат request body: `multipart/form-data`
- Поля:
  - `login`
  - `password`
  - `app_name`
- Значение `app_name` на текущем этапе фиксируется как `vetmanager-mcp`.
- `X-REST-API-KEY` для этого запроса не отправляется.

### 2. Runtime после exchange

- После успешного exchange сервис продолжает хранить только выданный
  `user_token`.
- Login/password не сохраняются в storage, логах, HTML и audit trail.
- Web UI для режима `login/password` больше не должен просить `api_key`.

### 3. Границы ответственности этапа 41

- `41.1` фиксирует корректный контракт token exchange.
- `41.2` обновляет backend exchange.
- `41.3` синхронизирует reauth flow.
- `41.4` убирает `api_key` из web wizard и copy/error messaging.
- `41.5–41.8` переписывают mock/unit/real/browser tests так, чтобы они
  проверяли именно новый контракт, а не устаревшее поведение.
- `41.9` синхронизирует README и технические артефакты.
- `41.10` завершает этап полным прогоном suite.

## Нецели

- Менять bearer-only MCP runtime.
- Переписывать storage-модель `user_token` на другой способ хранения.
- Внедрять новый Vetmanager auth mode сверх двух уже поддерживаемых.

## Декомпозиция

### 41.1 Контракт
- Зафиксировать `multipart/form-data` и поля `login/password/app_name`.
- Удалить предположение о необходимости `X-REST-API-KEY` для exchange.

### 41.2 Backend exchange
- Перевести `exchange_user_token()` на multipart form.
- Добавить `app_name=vetmanager-mcp`.
- Обновить safe error messages под новый контракт без упоминания `api_key`.

### 41.3 Reauth
- Использовать тот же exchange path для `/account/integration/reauth`.
- Не требовать `api_key` в payload.

### 41.4 Web UI
- В wizard и reauth-потоке убрать поле `api_key` для режима `login/password`.
- Сохранить явный privacy notice: логин и пароль используются только для
  получения user token.

### 41.5 Тесты backend/web
- Добавить red coverage на multipart exchange и `app_name`.
- Проверить отсутствие `api_key` в HTML, submit payload и safe errors.

### 41.6 Real e2e
- Разделить сценарии:
  - прямую валидацию уже готового `TEST_USER_TOKEN`;
  - отдельный обязательный `login/password exchange`.

### 41.7–41.8 Аудит честности тестов
- Убрать ложноположительные `skip` и сценарии, где flow объявлен рабочим без
  проверки реального exchange.
- Проверить остальные helper'ы на следование заявленному контракту.

### 41.9 Документация
- Обновить README, technical requirements и AssumptionLog.

### 41.10 Финальная валидация
- Выполнить полный прогон test suite после аудита и возможного рефакторинга.

## Критерии готовности

- В проекте есть PRD этапа 41.
- Контракт `token_auth.php` зафиксирован как `multipart/form-data` с
  `login/password/app_name`.
- В PRD явно закреплено, что `api_key` не участвует в login/password exchange.
- Следующие задачи этапа могут опираться на этот документ как на источник
  истины.
